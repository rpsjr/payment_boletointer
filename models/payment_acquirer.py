import re
import logging
import datetime

from odoo import api, fields, models
from odoo.http import request
from odoo.exceptions import UserError
from werkzeug import urls

_logger = logging.getLogger(__name__)
odoo_request = request

try:
    import iugu
except ImportError:
    _logger.exception("Não é possível importar iugu")

OPERATION_TYPE = [
    ('1', 'Boleto'),
]


class PaymentAcquirer(models.Model):
    _inherit = "payment.acquirer"

    provider = fields.Selection(selection_add=[("apiboletointer", "Boleto Inter")])

    bank_inter_cert = fields.Binary(string='Bank Inter Certificate')

    bank_inter_key = fields.Binary(string='Bank Inter Key')

    bank_inter_clientclientId = fields.Binary(string='Bank Inter ClientId')

    bank_inter_clientSecret = fields.Binary(string='Bank Inter ClientSecret')

    instrucoes = fields.Text('Instruções de cobrança')

    invoice_print = fields.Boolean(
        'Gerar relatorio na conclusão da fatura?')

    operation_type = fields.Selection(
        selection=OPERATION_TYPE,
        string='Tipo de Operação'
    )
