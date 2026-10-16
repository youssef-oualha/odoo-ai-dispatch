from odoo import models, fields

class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_created_by_ai = fields.Boolean(
        string="Généré par l'IA",
        default=False,
        readonly=True,
        help="Coché si ce contact a été créé automatiquement par l'intelligence artificielle."
    )