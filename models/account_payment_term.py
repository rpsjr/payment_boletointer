# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging

from odoo import fields, models, _
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)

class AcocuntPaymentTerm(models.Model):
    _inherit = 'account.payment.term'

    #note_boleto = fields.Text(string='Mensagem do boleto',
    #                            help='Campo para acrescentar instruções de pagamento no boleto')

    interst_mode = fields.Selection(
        selection=[("VALORDIA",'Valor fixo por dia'),("TAXAMENSAL",'Taxa mensal'),("ISENTO",'Isento')],
        string='Tipo de juros',
        default='ISENTO', required=True)

    interst_value = fields.Float('Valor/taxa de juros')

    fine_mode = fields.Selection(
        selection=[("NAOTEMMULTA",'Não tem'),("VALORFIXO",'Valor fixo'),("PERCENTUAL",'Taxa percentual')],
        string='Tipo de multa',
        default='NAOTEMMULTA', required=True)

    fine_value = fields.Float('Valor/taxa de multa')
