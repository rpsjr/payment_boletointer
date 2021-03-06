# © 2019 Danimar Ribeiro
# Part of OdooNext. See LICENSE file for full copyright and licensing details.
try:
    from erpbrasil.bank.inter.boleto import BoletoInter
    from erpbrasil.bank.inter.api import ApiInter
except ImportError:
    _logger.error("Biblioteca erpbrasil.bank.inter não instalada")

from .arquivo_certificado import ArquivoCertificado
from datetime import timedelta
from odoo import api, fields, models
from odoo.exceptions import UserError
import logging
_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    transaction_url = fields.Char(string="Url de Pagamento", size=256)
    origin_move_line_id = fields.Many2one('account.move.line')
    date_maturity = fields.Date(string="Data de Vencimento")

    pdf_boleto_id = fields.Many2one(
        comodel_name='ir.attachment',
        string='PDF Boleto',
        ondelete='cascade'
    )

    def generate_pdf_boleto(self):
        """
        Creates a new attachment with the Boleto PDF
        """
        if self.acquirer_reference and self.pdf_boleto_id:
            return

        with ArquivoCertificado(self.acquirer_id, 'w') as (key, cert):
            self.api = ApiInter(
                cert=(cert, key),
                conta_corrente=(self.acquirer_id.journal_id.bank_account_id.acc_number +
                                self.acquirer_id.journal_id.bank_account_id.acc_number_dig)
            )
            datas = self.api.boleto_pdf(self.acquirer_reference)
            self.pdf_boleto_id = self.env['ir.attachment'].create(
                {
                    'name': (
                        "Boleto %s.pdf" % self.display_name),
                    'datas': datas,
                    'type': 'binary'
                }
            )

    def print_pdf_boleto(self):
        """
        Generates and downloads Boletos PDFs
        :return: actions.act_url
        """

        self.generate_pdf_boleto()

        if self.acquirer_reference:
            boleto_id = self.pdf_boleto_id
            base_url = self.env['ir.config_parameter'].get_param(
                'web.base.url')
            download_url = '/web/content/%s/%s?download=True' % (
                str(boleto_id.id), boleto_id.name.replace('/','_'))

            return {
                "type": "ir.actions.act_url",
                "url": str(base_url) + str(download_url),
                "target": "new",
            }

    def cron_verify_transaction(self):
        documents = self.search([('state', 'in', ['draft', 'pending']), ], limit=50)
        for doc in documents:
            try:
                doc.action_verify_transaction()
                self.env.cr.commit()
            except Exception as e:
                self.env.cr.rollback()
                _logger.exception("Payment Transaction ID {}: {}.".format(
                    doc.id, str(e)), exc_info=True)

    def action_verify_transaction(self):
        if self.acquirer_id.provider != 'apiboletointer':
            return
        if not self.acquirer_reference:
            raise UserError('Esta transação não foi enviada a nenhum gateway de pagamento')

        with ArquivoCertificado(self.acquirer_id, 'w') as (key, cert):
            self.api = ApiInter(
                cert=(cert, key),
                conta_corrente=(self.acquirer_id.journal_id.bank_account_id.acc_number +
                                self.acquirer_id.journal_id.bank_account_id.acc_number_dig)
            )
            data = self.api.boleto_recupera(self.acquirer_reference)

        #EMABERTO, BAIXADO e VENCIDO e PAGO
        if "errors" in data or not data:
            raise UserError(data)
        if data['situacao'] == 'EMABERTO' and self.state  in ('draft'):
            self._set_transaction_pending()

        if data['situacao'] == 'PAGO' and self.state not in ('done', 'authorized'):
            self._set_transaction_done()
            self._post_process_after_done()
            #if self.origin_move_line_id:
                #self.origin_move_line_id._create_bank_tax_move(
                #    (data.get('taxes_paid_cents') or 0) / 100)
        #else:
            #self.iugu_status = data['status']

    def cancel_transaction_in_inter(self):
        if not self.acquirer_reference:
            raise UserError('Esta transação não foi enviada a nenhum gateway de pagamento')
        with ArquivoCertificado(self.acquirer_id, 'w') as (key, cert):
            self.api = ApiInter(
                cert=(cert, key),
                conta_corrente=(self.acquirer_id.journal_id.bank_account_id.acc_number +
                                self.acquirer_id.journal_id.bank_account_id.acc_number_dig)
            )
            data = self.api.boleto_baixa(self.acquirer_reference,'SUBISTITUICAO')


    def action_cancel_transaction(self):
        self._set_transaction_cancel()
        if self.acquirer_id.provider == 'apiboletointer':
            self.cancel_transaction_in_inter()
