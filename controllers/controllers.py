# from odoo import http


# class AiDispatch(http.Controller):
#     @http.route('/ai_dispatch/ai_dispatch', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/ai_dispatch/ai_dispatch/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('ai_dispatch.listing', {
#             'root': '/ai_dispatch/ai_dispatch',
#             'objects': http.request.env['ai_dispatch.ai_dispatch'].search([]),
#         })

#     @http.route('/ai_dispatch/ai_dispatch/objects/<model("ai_dispatch.ai_dispatch"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('ai_dispatch.object', {
#             'object': obj
#         })

