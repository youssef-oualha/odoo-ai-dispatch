from odoo import models, fields

class ProjectAiTagMapping(models.Model):
    _name = 'project.ai.tag.mapping'
    _description = 'Mapping des Tags IA vers Prestataires'
    _rec_name = 'crm_tag_id' 

    crm_tag_id = fields.Many2one(
        'crm.tag', 
        string='Catégorie IA (Tag CRM)', 
        required=True, 
        domain="[('is_ai_category', '=', True)]", # N'affiche que les tags IA
        ondelete='cascade',
        help="La catégorie CRM détectée par l'IA."
    )
    
    prestataire_tag_ids = fields.Many2many(
        'project.tags', 
        string='Étiquettes de Prestataire',
        help="Les tags prestataires ajoutés automatiquement à la tâche."
    )

    _sql_constraints = [
        ('unique_crm_tag_mapping', 'unique(crm_tag_id)', 'Une règle de mapping existe déjà pour ce tag CRM !')
    ]