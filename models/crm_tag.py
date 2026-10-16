from odoo import models, fields

class CrmTag(models.Model):
    _inherit = 'crm.tag'

    is_ai_category = fields.Boolean(
        string="Utilisé par l'IA", 
        default=False,
        help="Si coché, l'IA ajoutera cette catégorie à son vocabulaire d'analyse."
    )