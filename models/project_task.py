from odoo import models, fields, api

class ProjectTask(models.Model):
    _inherit = 'project.task'

    intervention_address = fields.Char(string="Adresse d'intervention")
    billing_address = fields.Char(string="Adresse de facturation")
    
    prestataire_tag_ids = fields.Many2many(
        'project.tags', 
        'project_task_prestataire_tag_rel', 
        'task_id', 'tag_id', 
        string="Étiquettes de Prestataire"
    )

    @api.onchange('tag_ids')
    def _onchange_tag_ids_sync_prestataires(self):
        """ Synchronise dynamiquement les tags prestataires en fonction des tags techniques """
        if not self.tag_ids:
            return

        # 1. Extraction des noms des tags actuels de la tâche
        tag_names = self.tag_ids.mapped('name')

        # 2. Recherche en BATCH (Une seule requête SQL au lieu d'une boucle)
        # Note: on compare par nom car la tâche utilise project.tags et le mapping utilise crm.tag
        mappings = self.env['project.ai.tag.mapping'].search([
            ('crm_tag_id.name', 'in', tag_names)
        ])
        
        if mappings:
            # 3. Extraction de tous les IDs prestataires via l'ORM Odoo
            new_prestataire_ids = mappings.mapped('prestataire_tag_ids').ids
            
            # 4. Fusion avec les tags existants pour ne pas écraser les ajouts manuels
            current_ids = self.prestataire_tag_ids.ids
            combined_ids = list(set(current_ids + new_prestataire_ids))
            
            self.prestataire_tag_ids = [(6, 0, combined_ids)]