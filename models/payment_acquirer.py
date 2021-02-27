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


class PaymentAcquirer(models.Model):
    _inherit = "payment.acquirer"

    provider = fields.Selection(selection_add=[("apiboletointer", "Boleto Inter")])

    bank_inter_cert = fields.Binary(string='Bank Inter Certificate')

    bank_inter_key = fields.Binary(string='Bank Inter Key')
