# 🤖 AI Dispatch - Module Intelligent pour Odoo 19

![Odoo Version](https://img.shields.io/badge/Odoo-19.0-purple?style=flat-square&logo=odoo)
![Python](https://img.shields.io/badge/Python-3.10+-blue?style=flat-square&logo=python)
![AI Powered](https://img.shields.io/badge/AI-LLM%20%26%20Vision-success?style=flat-square)

Ce document rassemble le guide opérationnel exhaustif à destination des utilisateurs finaux, le manuel de configuration système pour les administrateurs, ainsi que la documentation technique détaillée de l'architecture pour les équipes de développement.

---

## 📖 PARTIE I : Fonctionnalités & Guide Opérationnel

Ce module transforme le CRM standard d'Odoo en un centre de tri automatisé dopé à l'Intelligence Artificielle.

### 1. Réception et Analyse Multi-modale
Lorsqu'un client ou un outil externe envoie un email à l'adresse de support, un nouveau ticket est créé dans le CRM.
* **Extraction de Texte :** Le système nettoie la mise en forme (HTML, signatures) pour extraire l'essence de la demande.
* **Vision IA (OCR) :** Si des photos d'incidents, des scans de devis ou des bons d'intervention sont attachés, le modèle de Vision IA extrait contextuellement les informations des images (JPEG, PNG, PDF simples) pour enrichir l'analyse.
* **Exécution :** L'analyse peut être déclenchée manuellement via le bouton **"Analyser avec l'IA"** ou automatiquement à la création du ticket (selon la configuration).

### 2. Qualification et Exécution Automatique
En quelques secondes, l'IA catégorise la requête et génère les éléments opérationnels :
* **Demande d'Intervention :** Le ticket est qualifié, une tâche technique est générée dans le projet "INTERVENTIONS CLIENTS" avec les tags prestataires adéquats. Un Smart Button "Intervention" apparaît sur le CRM.
* **Demande de Devis :** Une Tâche Projet est générée dans "DEMANDE DEVIS CLIENTS" et le Smart Button "Devis" s'active.
* **Suivi / Annulation :** Reconnue par l'IA, cette catégorie ne génère aucune tâche pour ne pas polluer le planning des techniciens, et classe le ticket en *Suivi mail*.
* **Spam :** Identification et archivage des emails non pertinents.

### 3. Traçabilité, UX et Sécurités (Chatter Odoo)
Le système maintient une transparence totale via l'interface native d'Odoo :
* 🤖 **Badge "Contact IA" :** Identifie visuellement les fiches clients créées de toutes pièces par l'IA à partir des signatures d'emails.
* ✅ **Validation (Vert) :** Confirme la création réussie des tâches techniques.
* ⚠️ **Bouclier Anti-Doublon (Jaune) :** Stoppe la création de tâches multiples si un ticket similaire (même client, même catégorie) a été traité récemment.
* ℹ️ **Juge IA (Bleu) :** En cas de doute sur un doublon, une IA d'arbitrage compare sémantiquement les deux incidents pour confirmer s'il s'agit d'une simple relance ou d'un nouveau sinistre au même endroit.

---

## ⚙️ PARTIE II : Configuration Système (Administrateur)

Pour que l'automatisation fonctionne "Plug & Play", l'administrateur doit configurer les flux de messagerie et les clés API.

### 1. Configuration de la Messagerie Odoo
Le module s'appuie sur la passerelle mail d'Odoo pour capter et répondre aux requêtes.

**A. Serveur de messagerie entrant (IMAP)[cite: 10]**
Naviguez dans *Paramètres > Technique > Email > Serveurs de messagerie entrants* et configurez :
* **Nom :** incoming_test
* **Type de serveur :** Serveur IMAP
* **Nom du serveur :** `imap.gmail.com` (Port `993`, Sécurité `SSL/TLS` cochée)
* **Identifiants :** Email du support et Mot de passe d'application (16 caractères).
* **Action sur les emails entrants :** Dans "Créer un nouvel enregistrement", sélectionnez le modèle du CRM (`Demande d'intervention` / `crm.lead`) pour que chaque email génère un ticket.

**B. Serveur de messagerie sortant (SMTP)**
Naviguez dans *Paramètres > Technique > Email > Serveurs de messagerie sortants* :
* **Serveur SMTP :** `smtp.gmail.com` (Port `465`, Sécurité `SSL/TLS`).
* **Identifiants :** Mêmes accès que le serveur entrant pour garantir la délivrabilité des réponses automatiques.

### 2. Configuration des Fournisseurs IA (`ai.provider`)
Naviguez dans *Projet > Configuration > Fournisseurs IA* pour configurer vos modèles (OpenAI, DeepSeek, Qwen).
* **Sécurité RPC :** Les clés API saisies sont automatiquement masquées (`********`) lors des lectures via RPC grâce à une surcharge de la méthode `read()`.
* **Spécialisation :** Utilisez le toggle "Modèle de Vision" pour dédier un fournisseur spécifique à l'analyse d'images.
* **Sécurité d'exécution :** Une contrainte Python (`@api.constrains`) bloque l'activation simultanée de plusieurs modèles de même type pour éviter les conflits d'appels.

### 3. Mapping Dynamique des Tags (`project.ai.tag.mapping`)
L'interface de mapping remplace les algorithmes de routage statiques codés en dur. Naviguez dans *Projet > Configuration > Mapping Tags IA* pour associer dynamiquement les *Catégories IA* générées par le LLM (ex: "Plomberie") aux *Tags Prestataires* internes d'Odoo (ex: "Sanitaire").

---

## 🏗️ PARTIE III : Architecture Technique & Logique Métier

### 1. Pipeline de Traitement et Data Flow
1. **Fetchmail (Cron) :** L'action planifiée native d'Odoo relève les emails et génère les instances `crm.lead`.
2. **Nettoyage (Python) :** Purge des balises HTML via `tools.html2plaintext()` pour éviter d'intoxiquer le contexte du LLM.
3. **Inférence (API IA) :** Envoi du payload au fournisseur LLM avec un "System Prompt" coercitif.
4. **Post-Traitement & Sécurité :** Extraction JSON par Regex, application de la logique Zero-Trust, création du `res.partner` si absent, et assignation des adresses d'intervention.
5. **Action (Odoo) :** Génération des objets relationnels (`project.task`) et notification client.

### 2. Ingénierie du Prompt & Règles "Anti-Trap"
Le comportement de l'IA est bridé par des règles de résolution de conflits strictes :
* **Override d'Annulation :** Priorise sémantiquement les intentions d'annulation par rapport au lexique technique pour éviter les déplacements de techniciens inutiles.
* **Bypass de Génération Automatique :** Force l'analyse des sinistres même si l'email provient d'un automate (ex: tickets escaladés par Synergee ou Planon).
* **Graceful Fallback ("Autre") :** Si l'IA détecte un domaine hors base de données, elle est contrainte de retourner la catégorie de secours "Autre". Le backend intercepte, sécurise la contrainte SQL (Tag unique), et stationne le ticket pour révision humaine.

### 3. Sécurité d'Exécution ("Zero-Trust")
Le module ne fait jamais confiance aveuglément aux réponses de l'IA :
* **JSON Regex Strict :** Extraction robuste ciblant spécifiquement les blocs Markdown ou les accolades brutes.
* **Contrôle d'Intégrité :** En cas d'hallucination de données relationnelles, de JSON malformé (`JSONDecodeError`), de dépassement de quota (HTTP 429) ou de Timeout réseau, le système `try/except` injecte instantanément un dictionnaire métier de secours. Cela évite tout crash du serveur (Traceback) et bascule silencieusement le ticket en traitement manuel.

### 4. Surcharges ORM et UI/UX
* **Modèles `crm.lead` & `project.task` :** Extension des modèles pour inclure la géolocalisation de l'intervention (`intervention_address`), la langue (`detected_language`) et le traçage exact du type d'entité générée (`task_type`).
* **Synchronisation Dynamique (`@api.onchange`) :** L'ajout ou la modification d'un tag métier déclenche la mise à jour en temps réel des tags prestataires sur la Tâche, facilitant le travail de dispatch manuel.
* **Intégration CSS (Odoo Grids) :** Résolution des conflits d'affichage de la grille Odoo native (`<group>`) par l'encapsulation de composants Bootstrap (`d-flex`, `o_row`, `flex-grow-1`). Les badges IA ("Contact IA", statut d'analyse) sont parfaitement intégrés sans débordement ni troncature de texte.

---
**Développé par :** Youssef Oualha  
Étudiant en double-diplôme d'ingénieur (Cybersécurité à Télécom Paris & Télécommunications à l'ENIT).
