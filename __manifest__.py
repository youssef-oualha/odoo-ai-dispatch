{
    'name': "ai_dispatch",

    'summary': "Short (1 phrase/line) summary of the module's purpose",

    'description': """
Long description of module's purpose
    """,

    'author': "My Company",
    'website': "https://www.yourcompany.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/15.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'Uncategorized',
    'version': '0.2',

    # any module necessary for this one to work correctly
    'depends': ['base','mail','crm','project'],

    # always loaded
    'data': [
        'security/ir.model.access.csv',
        'views/ai_provider_views.xml',
        'views/crm_lead_views.xml',
        'views/crm_tag_views.xml',
        'views/project_task_views.xml',
        'views/odoo_native_overrides.xml',
        'views/ai_tag_mapping_views.xml',
        'views/res_partner_views.xml'
    ],
    # only loaded in demonstration mode
    'demo': [
        'demo/demo.xml',
    ],
    'installable': True,
    'application': True,
}

