from odoo import models, fields, api
from odoo.exceptions import ValidationError

class AiProvider(models.Model):
    _name = 'ai.provider'
    _description = 'Configuration du Fournisseur IA'

    name = fields.Char(string="Nom du Fournisseur", required=True)
    base_url = fields.Char(string="URL de base API", required=True)
    api_key = fields.Char(string="Clé API", required=True)
    
    model_name = fields.Char(string="Nom du Modèle", required=True)
    is_active = fields.Boolean(string="Actif", default=False)
    
    is_vision_model = fields.Boolean(
        string="Modèle de Vision (OCR / Images)", 
        default=False,
        help="Dédie ce fournisseur à l'analyse des pièces jointes et images."
    )
    
    auto_analyze_leads = fields.Boolean(
        string="Analyse automatique", 
        default=False,
        help="Déclenche l'IA automatiquement à la création d'un Lead."
    )

    def read(self, fields=None, load='_classic_read'):
        """ Empêche la clé API d'être renvoyée en clair via RPC """
        records = super().read(fields, load)
        if fields and 'api_key' in fields:
            for record in records:
                if record.get('api_key'):
                    record['api_key'] = '********'
        return records

    @api.constrains('is_active', 'is_vision_model')
    def _check_single_active_provider(self):
        """ Garantit qu'il n'y a qu'un seul modèle actif par catégorie """
        for record in self:
            if record.is_active:
                domain = [
                    ('is_active', '=', True),
                    ('is_vision_model', '=', record.is_vision_model),
                    ('id', '!=', record.id)
                ]
                if self.search_count(domain) > 0:
                    model_type = "Vision" if record.is_vision_model else "Principal"
                    raise ValidationError(f"Vous ne pouvez avoir qu'un seul modèle {model_type} actif à la fois.")