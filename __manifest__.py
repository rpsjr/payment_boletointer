# © 2018 Danimar Ribeiro, Trustcode
# Part of Trustcode. See LICENSE file for full copyright and licensing details.


{
    'name': 'Cobrança Banco Inter',
    'version': '13.0.1.0.0',
    'category': 'Finance',
    'sequence': 5,
    'author': 'T',
    'license': 'OPL-1',
    'summary': """Realiza a integração com API Cobrança Banco Inter""",
    'website': 'https://www..com.br',
    'support': 'comercial@.com.br',
    'contributors': [
        'Danimar Ribeiro <danimaribeiro@gmail.com>',
        'Raimundo'
    ],
    'depends': [
        'account',
        'l10n_br_base_address',
    ],
    'external_dependencies': {
        'python': [
            'erpbrasil.bank.inter',
        ],
    },
    'data': [
        'data/verify_transaction_cron.xml',
        'data/payment_acquirer.xml',
        'views/res_company.xml',
        'views/account_move.xml',
        'views/account_journal.xml',
        'views/payment_acquirer.xml',
        'views/portal_templates.xml',
        'views/res_config_settings.xml',
        'wizard/wizard_iugu.xml',
        'wizard/wizard_new_payment.xml',
    ],
}
