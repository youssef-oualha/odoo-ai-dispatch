from odoo import models, fields, api, tools
from odoo.exceptions import UserError
import json
import requests
import logging
import re
import fitz
import base64
from datetime import timedelta

_logger = logging.getLogger(__name__)

class CrmLead(models.Model):
    _inherit = 'crm.lead'

    # =========================================================================
    # DÉCLARATION DES CHAMPS
    # =========================================================================
    ai_status = fields.Selection([
        ('pending', 'À analyser'),
        ('done', 'Analysé par IA')
    ], string="Statut IA", default='pending')

    ai_request_type = fields.Selection([
        ('intervention', "Demande d'intervention"),
        ('quote', 'Demande de devis'),
        ('followup', 'Suivi / Relance'),
        ('info_request', "Demande d'information"),
        ('notification', 'Notification système'),
        ('spam', 'Spam'),
        ('other', 'Autre / Indéterminé')
    ], string="Type de demande (IA)", readonly=True)

    intervention_address = fields.Char(string="Adresse d'intervention (IA)")
    billing_address = fields.Char(string="Adresse de facturation (IA)")
    detected_language = fields.Char(string="Langue détectée (IA)")
    
    task_id = fields.Many2one('project.task', string="Tâche d'intervention liée", readonly=True)
    task_type = fields.Selection([
        ('intervention', 'Intervention'),
        ('quote', 'Devis')
    ], string="Type de Tâche Générée", readonly=True)
    partner_is_created_by_ai = fields.Boolean(
        related='partner_id.is_created_by_ai', 
        string="Contact IA", 
        readonly=True
    )

    # =========================================================================
    # MÉTHODE PRINCIPALE : ORCHESTRATION DE L'IA
    # =========================================================================
    def action_analyze_with_ai(self):
        """ Orchestre l'analyse IA du Lead : Extraction, Vision, Classification, Doublons """
        for record in self:
            _logger.info(f"Starting Robust AI analysis for Lead: {record.name}")
            
            # 1. Vérification des prérequis
            provider, vision_provider = self._get_ai_providers()
            
            # 2. Préparation du texte principal (Nettoyage HTML agressif)
            raw_desc = record.description or ''
            clean_desc = tools.html2plaintext(raw_desc) if '<' in raw_desc and '>' in raw_desc else raw_desc
            
            text_to_analyze = f"SUJET DE L'EMAIL : {record.name}\n\nCORPS DU MESSAGE :\n{clean_desc}"
            
            # 3. Traitement des pièces jointes & Appel Vision IA
            attachment_text, images_payload = self._process_attachments(record)
            if images_payload and vision_provider:
                vision_summary = self._analyze_images_with_vision(images_payload, vision_provider)
                attachment_text += vision_summary
            
            if attachment_text:
                text_to_analyze += f"\n\n{attachment_text}"
            if not text_to_analyze.strip():
                text_to_analyze = record.name

            _logger.warning(f"--- TEXT SENT TO AI ---\n{text_to_analyze}\n-----------------------")

            # 4. Appel de l'IA principale pour la classification
            parsed_data = self._classify_text_with_ai(text_to_analyze, provider)

            # 5. Création/Mise à jour du contact intelligent
            record._handle_smart_contact_creation(parsed_data)

            # 6. Vérification intelligente des doublons
            parsed_data = self._handle_duplicate_check(record, parsed_data, text_to_analyze, provider)

            # 7. Mise à jour de la base de données (Tags, Etapes, Création de tâche)
            self._apply_ai_results_to_record(record, parsed_data)

    # =========================================================================
    # SOUS-MÉTHODES : LOGIQUE MÉTIER & APPELS API (Refactoring SRP)
    # =========================================================================
    def _get_ai_providers(self):
        """ Récupère les fournisseurs d'IA (Texte et Vision) """
        provider = self.env['ai.provider'].search([('is_active', '=', True), ('is_vision_model', '=', False)], limit=1)
        vision_provider = self.env['ai.provider'].search([('is_vision_model', '=', True), ('is_active', '=', True)], limit=1)
        if not provider or not provider.api_key:
            raise UserError("Aucun fournisseur IA actif ou clé API manquante !")
        return provider, vision_provider

    def _process_attachments(self, record, max_attachments=2):
        """ Traite les PDF et le Texte, prépare les images pour la Vision """
        attachments = self.env['ir.attachment'].search([('res_model', '=', 'crm.lead'), ('res_id', '=', record.id)])
        
        # Tri : PDF et texte en priorité
        sorted_attachments = sorted(attachments, key=lambda a: 0 if a.mimetype == 'application/pdf' or (a.mimetype and a.mimetype.startswith('text/')) else 1)
        
        attachment_text = ""
        images_payload = []
        processed_count = 0

        for att in sorted_attachments:
            if processed_count >= max_attachments:
                _logger.info(f"Limite de {max_attachments} PJ atteinte. Les suivantes sont ignorées.")
                break
                
            mime = att.mimetype or ''
            
            if mime == 'application/pdf':
                extracted_text = att.index_content or ''
                if len(extracted_text.strip()) > 50:
                    attachment_text += f"\n--- Document PDF ({att.name}) ---\n{extracted_text}\n"
                    processed_count += 1
                elif att.raw:
                    # PDF scanné -> Conversion en image
                    try:
                        doc = fitz.open(stream=att.raw, filetype="pdf")
                        if len(doc) > 0:
                            pix = doc[0].get_pixmap(dpi=96)
                            b64_str = base64.b64encode(pix.tobytes("png")).decode('utf-8')
                            images_payload.append({'mime': 'image/png', 'base64': b64_str, 'name': f"{att.name} (Page 1)"})
                            processed_count += 1
                            _logger.info(f"PDF scanné '{att.name}' converti en image.")
                    except Exception as e:
                        _logger.error(f"Erreur conversion PDF {att.name}: {e}")
                        
            elif mime.startswith('text/'):
                raw_text = att.raw.decode('utf-8', errors='ignore') if att.raw else ''
                attachment_text += f"\n--- Texte ({att.name}) ---\n{raw_text}\n"
                processed_count += 1
                
            elif mime.startswith('image/') and att.datas and processed_count < max_attachments:
                b64_data = att.datas.decode('utf-8') if isinstance(att.datas, bytes) else att.datas
                images_payload.append({'mime': mime, 'base64': b64_data, 'name': att.name})
                processed_count += 1

        return attachment_text, images_payload

    def _analyze_images_with_vision(self, images_payload, provider):
        """ Envoie les images au modèle de vision et retourne le résumé """
        _logger.info(f"Envoi de {len(images_payload)} image(s) au modèle Vision.")
        
        content_array = [{"type": "text", "text": self._get_vision_prompt()}]
        for img in images_payload:
            content_array.append({
                "type": "image_url",
                "image_url": {"url": f"data:{img['mime']};base64,{img['base64']}"}
            })

        payload = {
            "model": provider.model_name,
            "messages": [{"role": "user", "content": content_array}],
            "max_tokens": 1024,
            "temperature": 0.1
        }
        
        try:
            response_text = self._make_api_request(provider, payload, timeout=60)
            _logger.info("Analyse Vision IA réussie.")
            return f"\n\n--- [RÉSUMÉ VISION IA (Documents scannés & Photos)] ---\n{response_text}\n"
        except Exception as e:
            _logger.error(f"Erreur Vision IA: {e}")
            return f"\n\n[ERREUR VISION IA : {str(e)}]\n"

    def _classify_text_with_ai(self, text_to_analyze, provider):
        """ Appelle l'IA de classification principale et parse le résultat JSON """
        ai_tags = self.env['crm.tag'].search([('is_ai_category', '=', True)])
        allowed_categories = ai_tags.mapped('name') or []
        
        # FIX : La porte de sortie "Autre" doit TOUJOURS être dans les choix
        if "Autre" not in allowed_categories:
            allowed_categories.append("Autre")
            
        categories_string = ", ".join(allowed_categories)

        payload = {
            "model": provider.model_name,
            "messages": [
                {"role": "system", "content": self._get_classification_prompt(categories_string)},
                {"role": "user", "content": f"Extract info from this email:\n{text_to_analyze}"}
            ],
            "temperature": 0.1,
            "max_tokens": 2500  
        }

        try:
            content = self._make_api_request(provider, payload, timeout=15)
            _logger.info(f"AI Raw Response: {content}")
            return self._extract_json_from_response(content)
        except Exception as e:
            _logger.error(f"Echec de la classification IA: {e}")
            return self._get_fallback_json(str(e))

    def _handle_duplicate_check(self, record, parsed_data, text_to_analyze, provider):
        """ 🚨 CHECK ANTI-DOUBLON INTELLIGENT (DOUBLE VALIDATION IA) """
        current_request = parsed_data.get('request_type')
        category = parsed_data.get('category')

        if current_request in ['intervention', 'quote']:
            duplicate = record._detect_duplicate_request(category)
            if duplicate:
                _logger.info(f"Suspicion de doublon détectée avec {duplicate.name}. Vérification IA...")
                
                prompt = self._get_duplicate_prompt(duplicate, text_to_analyze)
                payload = {
                    "model": provider.model_name,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.0
                }
                
                is_duplicate_confirmed = True # Sécurité par défaut
                try:
                    response_text = self._make_api_request(provider, payload, timeout=10)
                    dup_data = self._extract_json_from_response(response_text)
                    is_duplicate_confirmed = dup_data.get('is_duplicate', True)
                except Exception as e:
                    _logger.error(f"Erreur IA lors de la vérification du doublon : {e}")

                if is_duplicate_confirmed:
                    parsed_data['request_type'] = 'followup' 
                    record.message_post(
                        body=f"<b>Doublon confirmé par l'IA :</b> Ticket passé en 'Suivi'. Relatif à : <a href='#' data-oe-model='crm.lead' data-oe-id='{duplicate.id}'>{duplicate.name}</a>."
                    )
                else:
                    record.message_post(
                        body=f"ℹ <b>Suspicion de doublon levée par l'IA :</b> NOUVELLE intervention distincte du ticket <a href='#' data-oe-model='crm.lead' data-oe-id='{duplicate.id}'>{duplicate.name}</a>."
                    )
        return parsed_data

    def _apply_ai_results_to_record(self, record, parsed_data):
        """ Applique les résultats de l'IA (mise à jour du Lead, création de tâches) """
        category = parsed_data.get('category')
        tag_commands = []
        category = parsed_data.get('category')
        tag_commands = []
        if category and str(category).strip().lower() not in ['null', 'none', '']:
            clean_category = str(category).strip()
            
            # ✅ On cherche la catégorie exacte ET on vérifie qu'elle fait bien partie des tags IA
            crm_tag = self.env['crm.tag'].search([
                ('name', '=ilike', clean_category),
                ('is_ai_category', '=', True)
            ], limit=1)
            
            if crm_tag:
                tag_commands = [(4, crm_tag.id)]
            else:
                _logger.warning(f"L'IA a inventé ou mal orthographié la catégorie : '{clean_category}'.")
                
                # FIX : Cherche le tag "Autre" globalement, peu importe son statut IA
                fallback_tag = self.env['crm.tag'].search([('name', '=ilike', 'Autre')], limit=1)
                
                if fallback_tag:
                    # S'il existe mais n'est pas "IA", on l'active silencieusement
                    if not fallback_tag.is_ai_category:
                        fallback_tag.is_ai_category = True
                else:
                    # S'il n'existe vraiment pas du tout, on le crée
                    fallback_tag = self.env['crm.tag'].create({
                        'name': 'Autre', 
                        'is_ai_category': True, 
                        'color': 1  # Rouge pour attirer l'attention
                    })
                    
                tag_commands = [(4, fallback_tag.id)]

        ai_priority = str(parsed_data.get('priority')).strip().lower()
        odoo_priority = '3' if ai_priority in ['high', 'critical'] else '2' if ai_priority == 'medium' else '1'

        stage_mapping = {
            'intervention': "Demande d'intervention", 'quote': 'Demande de devis',
            'followup': 'Suivi mail', 'info_request': 'Nouveau',
            'notification': 'Nouveau', 'other': 'Nouveau', 'spam': 'Spam'
        }
        
        target_stage_name = stage_mapping.get(parsed_data.get('request_type'))
        new_stage_id = False
        
        if target_stage_name and target_stage_name != 'Spam':
            stage = self.env['crm.stage'].search([('name', '=', target_stage_name)], limit=1)
            if not stage:
                sequence = list(stage_mapping.keys()).index(parsed_data.get('request_type')) + 2 
                stage = self.env['crm.stage'].create({'name': target_stage_name, 'sequence': sequence})
            new_stage_id = stage.id

        summary = f"**Résumé IA :** {parsed_data.get('description', 'N/A')}\n\n"
        if parsed_data.get('intervention_address'):
            summary += f"**📍 Adresse Intervention :** {parsed_data.get('intervention_address')}\n"
        if parsed_data.get('billing_address'):
            summary += f"**🧾 Adresse Facturation :** {parsed_data.get('billing_address')}\n"
        
        update_vals = {
            'ai_status': 'done',
            'ai_request_type': parsed_data.get('request_type'),
            'priority': odoo_priority,
            'description': summary + (record.description or ""),
            'type': 'opportunity',
            'intervention_address': parsed_data.get('intervention_address'),
            'billing_address': parsed_data.get('billing_address'),
            'detected_language': parsed_data.get('language'),
        }
        
        if new_stage_id:
            update_vals['stage_id'] = new_stage_id 
        if tag_commands:
            update_vals['tag_ids'] = tag_commands
            
        record.write(update_vals)
        
        # Actions post-sauvegarde
        if record.ai_request_type == 'spam':
            record.active = False
            record.message_post(body="🚫 Spam détecté par l'IA. Piste archivée.")
        elif record.ai_request_type in ['intervention', 'quote']:
            record_type_name = "technique" if record.ai_request_type == 'intervention' else "de devis"
            record.message_post(body=f"✅ Analyse IA réussie. Création de la tâche {record_type_name}...")
            record._create_project_task()
            record._send_auto_reply()
        else:
            record.message_post(body="✅ Analyse IA réussie. Tags et Priorité mis à jour.")
            record._send_auto_reply()

    # =========================================================================
    # FONCTIONS UTILITAIRES (API, JSON, Prompts)
    # =========================================================================
    def _make_api_request(self, provider, payload, timeout=15):
        """ Gère les appels HTTP standardisés vers les fournisseurs IA """
        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8069", 
            "X-Title": "Odoo 19 AI Dispatch" 
        }
        api_url = f"{provider.base_url.rstrip('/')}"
        if not api_url.endswith('chat/completions'):
            api_url += "/chat/completions"
            
        response = requests.post(api_url, headers=headers, json=payload, timeout=timeout)
        if not response.ok:
            raise ValueError(f"Erreur API {response.status_code}: {response.text}")
            
        # 1. On récupère le JSON brut de la réponse
        result_json = response.json()
        
        # 2. On extrait le contenu (peut être None si bloqué par un filtre Azure/OpenAI)
        raw_content = result_json.get('choices', [{}])[0].get('message', {}).get('content')
        
        # 3. Sécurité absolue : on convertit None en chaîne vide avant le strip()
        content = (raw_content or "").strip()
        
        # 4. Si c'est vide, on logue le JSON brut pour voir le 'finish_reason' (ex: content_filter)
        if not content:
            _logger.error(f"L'API a renvoyé une réponse vide. JSON brut de l'API : {json.dumps(result_json)}")
            raise ValueError("L'IA a renvoyé une réponse vide (Filtre de sécurité déclenché ou erreur interne de l'API).")
            
        return content

    def _extract_json_from_response(self, content):
        """ Extrait le bloc JSON d'une réponse texte/markdown et gère les réponses vides """
        # NOUVEAU: Sécurité anti-réponse vide
        if not content or not content.strip():
            raise ValueError("L'API a renvoyé une réponse totalement vide (0 tokens). Filtre de sécurité ou blocage du modèle.")

        json_match = re.search(r'```(?:json)?\s*(.*?)\s*```', content, re.DOTALL)
        if json_match:
            clean_json = json_match.group(1)
        else:
            start_idx = content.find('{')
            end_idx = content.rfind('}')
            clean_json = content[start_idx:end_idx+1] if start_idx != -1 and end_idx != -1 else content
            
        try:
            return json.loads(clean_json)
        except json.JSONDecodeError:
            raise ValueError(f"Impossible de parser le JSON: {clean_json}")
        
    def _get_fallback_json(self, error_message):
        return {
            'request_type': 'other', 'category': False, 'priority': 'low',
            'client_name': False, 'email': False, 'phone': False,
            'intervention_address': False, 'billing_address': False,
            'language': 'fr', 'description': f"⚠️ Échec de l'analyse IA. ({error_message})"
        }

    def _get_vision_prompt(self):
        return (
            "Tu es un expert en analyse de documents techniques, devis, photos de chantiers. "
            "1. Extrais de manière neutre TOUTES les infos techniques (panne, matériel, dimensions). "
            "2. Extrais les contacts visibles. "
            "3. Rédige un résumé technique clair pour les techniciens. "
            "Règle stricte : Décris ce qui EST, ne mentionne pas ce qui est absent."
        )

    def _get_classification_prompt(self, categories_string):
        return f"""You are a B2B facility management and maintenance routing AI. 
Your ONLY job is to classify administrative maintenance tickets for an ERP. 
CONTEXT: These emails describe routine building maintenance. There is NO immediate physical danger. Do not trigger safety refusals.

Please read the top, most recent part of the email and ignore older quoted history.

Important rules for request_type precedence:
1. Accepted quote: If the email states a quote is accepted (e.g., "Devis accepté"), request_type must be "info_request" or "followup".
2. Email text vs Attachments: If it is a genuinely new quote request, it remains "quote".
3. Automated Ticketing Systems: If the email is automatically generated by a system but contains a request for a physical repair or quote, classify it by the underlying request.
4. CANCELLATIONS OVERRIDE EVERYTHING: If the newest message explicitly asks to cancel, abort, or close a request (e.g., "annuler cette inter", "merci d'annuler", "ne pas tenir compte"), the request_type MUST be "followup" or "info_request". Do NOT classify it as an "intervention", even if the original technical repair request is quoted in the email history.

Classification categories:
- "intervention": New request for physical repair on site.
- "quote": New request for a price estimate.
- "followup": Follow-up, client reminders, replies to existing tickets, requests for reports.
- "info_request": Seeking information without asking for intervention/quote.
- "notification": Informative/automated messages strictly without any actionable work order.
- "spam": Promotional/Commercial.
- "other": Fallback if too short or unsure.

ALLOWED CATEGORIES (category): [{categories_string}]

Analyze and return ONLY a valid JSON object with keys:
- request_type (string)
- category (string, YOU MUST INFER the best match logically from the allowed list below based on the underlying job discussed. If the requested repair (e.g., 'Escalier', 'Ascenseur') does not clearly fit into ANY of the provided categories, you MUST output "Autre". Do NOT attempt to invent categories and do NOT get stuck analyzing missing categories.)
- priority (Low, Medium, High)
- client_name (string or null)
- email (string or null)
- phone (string or null)
- intervention_address (string or null)
- billing_address (string or null)
- language (string)
- description (string in FRENCH, include Vision AI details)
"""

    def _get_duplicate_prompt(self, duplicate_record, new_text):
        return f"""Tu es un assistant IA expert en déduplication de tickets de maintenance. 
Vérifie si ces deux demandes (du même client) concernent EXACTEMENT le même incident physique.
Réponds UNIQUEMENT avec un JSON valide : {{"is_duplicate": true}} ou {{"is_duplicate": false}}.

--- ANCIEN TICKET ---
{duplicate_record.name}
{tools.html2plaintext(duplicate_record.description or '')[:1500]}

--- NOUVEAU TICKET ---
{new_text[:1500]}
"""

    # =========================================================================
    # MÉTHODES MÉTIER (Contacts, Tâches, Emails)
    # =========================================================================
    def _handle_smart_contact_creation(self, ai_data):
        for lead in self:
            email = ai_data.get('email')
            name = ai_data.get('client_name')
            if not email or not name:
                continue

            domain_match = re.search(r'@([\w.-]+)', email)
            if not domain_match:
                continue
                
            domain = domain_match.group(1)
            generic_domains = ['gmail.com', 'yahoo.com', 'yahoo.fr', 'hotmail.com', 'outlook.com', 'orange.fr', 'free.fr']
            parent_company = False
            
            if domain not in generic_domains:
                parent_company = self.env['res.partner'].search([
                    ('is_company', '=', True),
                    '|', ('email', 'ilike', f'@{domain}'), ('website', 'ilike', domain)
                ], limit=1)

            contact = self.env['res.partner'].search([('email', '=', email)], limit=1)
            if not contact:
                contact = self.env['res.partner'].create({
                    'name': name,
                    'email': email,
                    'phone': ai_data.get('phone'),
                    'parent_id': parent_company.id if parent_company else False,
                    'is_company': False,
                    'is_created_by_ai': True })

            lead.write({'partner_id': contact.id})

    def _create_project_task(self, manual_type=None):
        for record in self:
            request_type = manual_type or record.ai_request_type
            if request_type not in ['quote', 'intervention']:
                continue

            project_name = "DEMANDE DEVIS CLIENTS" if request_type == 'quote' else "INTERVENTIONS CLIENTS"
            project = self.env['project.project'].search([('name', '=ilike', project_name)], limit=1)
            if not project:
                project = self.env['project.project'].create({'name': project_name})

            task_tag_ids = []
            task_prestataire_tag_ids = []
            
            if record.tag_ids:
                for crm_tag in record.tag_ids:
                    proj_tag = self.env['project.tags'].search([('name', '=ilike', crm_tag.name)], limit=1)
                    if not proj_tag:
                        proj_tag = self.env['project.tags'].create({'name': crm_tag.name})
                    task_tag_ids.append((4, proj_tag.id))

                    mapping = self.env['project.ai.tag.mapping'].search([('crm_tag_id.name', '=ilike', crm_tag.name)], limit=1)
                    if mapping:
                        for p_tag in mapping.prestataire_tag_ids:
                            task_prestataire_tag_ids.append((4, p_tag.id))

            task = self.env['project.task'].create({
                'name': record.name,
                'project_id': project.id,
                'partner_id': record.partner_id.id if record.partner_id else False,
                'description': record.description,
                'priority': record.priority,
                'intervention_address': record.intervention_address,
                'billing_address': record.billing_address,
                'tag_ids': task_tag_ids if task_tag_ids else False,
                'prestataire_tag_ids': task_prestataire_tag_ids if task_prestataire_tag_ids else False,
            })
            
            record.write({
                'task_id': task.id,
                'task_type': request_type
            })
            record.message_post(body=f"✅ Tâche générée automatiquement dans le projet '{project.name}'.")

    def _send_auto_reply(self):
        for record in self:
            if not record.email_from:
                continue

            subject = f"Accusé de réception : {record.name}"
            body = ""

            if record.ai_request_type == 'intervention':
                body = f"Bonjour {record.partner_name or ''},<br><br>Nous avons bien reçu votre demande d'intervention technique. Une tâche prioritaire a été générée.<br><br>Cordialement,<br>L'équipe Support technique"
            elif record.ai_request_type == 'quote':
                body = f"Bonjour {record.partner_name or ''},<br><br>Votre demande de devis a bien été transmise à notre service commercial.<br><br>Cordialement,<br>L'équipe Commerciale"
            elif record.ai_request_type == 'info_request':
                body = f"Bonjour {record.partner_name or ''},<br><br>Nous avons bien pris en compte votre demande d'information. Un conseiller va vous répondre sous peu.<br><br>Cordialement,<br>L'équipe Relation Client"

            if body:
                record.message_post(
                    body=body, subject=subject, message_type='comment', subtype_xmlid='mail.mt_comment'
                )

    def _detect_duplicate_request(self, category_name):
        self.ensure_one()
        if not self.partner_id:
            return False

        date_limit = fields.Datetime.now() - timedelta(days=15)
        domain = [
            ('id', '!=', self.id),
            ('partner_id', '=', self.partner_id.id),
            ('create_date', '>=', date_limit),
            ('ai_request_type', 'in', ['intervention', 'quote'])
        ]
        if category_name:
            domain.append(('tag_ids.name', '=ilike', category_name))

        return self.env['crm.lead'].search(domain, limit=1)

    # =========================================================================
    # SURCHARGES ODOO & ACTIONS UI
    # =========================================================================
    @api.model_create_multi
    def create(self, vals_list):
        leads = super().create(vals_list)
        provider = self.env['ai.provider'].search([('is_active', '=', True)], limit=1)
        if provider and provider.auto_analyze_leads:
            _logger.info("Auto-analysis toggle is ON. Running AI...")
            for lead in leads:
                try:
                    lead.action_analyze_with_ai()
                except Exception as e:
                    _logger.warning(f"Automatic AI analysis failed for lead ID {lead.id}: {str(e)}")
        return leads

    @api.model
    def message_new(self, msg_dict, custom_values=None):
        custom_values = custom_values or {}
        email_subject = msg_dict.get('subject', 'Sans objet')
        email_from = msg_dict.get('from') or msg_dict.get('email_from', 'Inconnu')
        raw_body_html = msg_dict.get('body', '')
        clean_body = tools.html2plaintext(raw_body_html) if raw_body_html else ''
        
        full_text = f"Sujet : {email_subject}\nExpéditeur : {email_from}\n---\n{clean_body}"
        custom_values['description'] = full_text
        
        return super(CrmLead, self).message_new(msg_dict, custom_values)

    def action_view_task(self):
        self.ensure_one()
        if self.task_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'project.task',
                'res_id': self.task_id.id,
                'view_mode': 'form',
                'target': 'current',
            }

    def action_create_manual_intervention(self):
        for record in self:
            record._create_project_task(manual_type='intervention')
            stage = self.env['crm.stage'].search([('name', 'ilike', "Demande d'intervention")], limit=1)
            if stage:
                record.stage_id = stage.id
            record.message_post(body="🛠️ Tâche d'intervention créée manuellement. Piste avancée.")

    def action_create_manual_devis(self):
        for record in self:
            record._create_project_task(manual_type='quote')
            stage = self.env['crm.stage'].search([('name', 'ilike', "Demande de devis")], limit=1)
            if stage:
                record.stage_id = stage.id
            record.message_post(body="📄 Tâche de devis créée manuellement. Piste avancée.")