# © 2019 Danimar Ribeiro
# Part of OdooNext. See LICENSE file for full copyright and licensing details.

import iugu
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

        order_id = self.payment_line_ids[0].order_id
        self.payment_mode_id
        with ArquivoCertificado(self.payment_mode_id, 'w') as (key, cert):
            self.api = ApiInter(
                cert=(cert, key),
                conta_corrente=(self.payment_mode_id.fixed_journal_id.bank_account_id.acc_number +
                                self.payment_mode_id.fixed_journal_id.bank_account_id.acc_number_dig)
            )
            datas = self.api.boleto_pdf(self.acquirer_reference)
            self.pdf_boleto_id = self.env['ir.attachment'].create(
                {
                    'name': (
                        "Boleto %s" % self.bank_payment_line_id.display_name),
                    'datas': datas,
                    'datas_fname': ("boleto_%s.pdf" %
                                    self.bank_payment_line_id.display_name),
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
                str(boleto_id.id), boleto_id.name)

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
        if self.acquirer_id.provider != 'iugu':
            return
        if not self.acquirer_reference:
            raise UserError('Esta transação não foi enviada a nenhum gateway de pagamento')
        token = self.env.company.iugu_api_token
        iugu.config(token=token)
        iugu_invoice_api = iugu.Invoice()

        data = iugu_invoice_api.search(self.acquirer_reference)
        if "errors" in data:
            raise UserError(data['errors'])
        if data.get('status', '') == 'paid' and self.state not in ('done', 'authorized'):
            self._set_transaction_done()
            self._post_process_after_done()
            if self.origin_move_line_id:
                self.origin_move_line_id._create_bank_tax_move(
                    (data.get('taxes_paid_cents') or 0) / 100)
        else:
            self.iugu_status = data['status']

    def cancel_transaction_in_iugu(self):
        if not self.acquirer_reference:
            raise UserError('Esta parcela não foi enviada ao IUGU')
        token = self.env.company.iugu_api_token
        iugu.config(token=token)
        iugu_invoice_api = iugu.Invoice()
        iugu_invoice_api.cancel(self.acquirer_reference)

    def action_cancel_transaction(self):
        self._set_transaction_cancel()
        if self.acquirer_id.provider == 'iugu':
            self.cancel_transaction_in_iugu()
