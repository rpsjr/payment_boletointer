# © 2019 Danimar Ribeiro
# Part of OdooNext. See LICENSE file for full copyright and licensing details.


import base64
import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

from .arquivo_certificado import ArquivoCertificado

_logger = logging.getLogger(__name__)

try:
    from erpbrasil.bank.inter.api import ApiInter
    from erpbrasil.bank.inter.boleto import BoletoInter
except ImportError:
    _logger.error("Biblioteca erpbrasil.bank.inter não instalada")


class PaymentTransaction(models.Model):
    _inherit = "payment.transaction"

    transaction_url = fields.Char(string="Url de Pagamento", size=256)
    origin_move_line_id = fields.Many2one("account.move.line")
    date_maturity = fields.Date(string="Data de Vencimento")

    pdf_boleto_id = fields.Many2one(
        comodel_name="ir.attachment", string="PDF Boleto", ondelete="cascade"
    )

    def _isBase64(self, sb):
        try:
            if isinstance(sb, str):
                # If there's any unicode here, an exception will be thrown and the function will return false
                sb_bytes = bytes(sb, "ascii")
                # _logger.error("my sb_bytes : %r", sb_bytes)
            elif isinstance(sb, bytes):
                sb_bytes = sb
                # _logger.error("my sb_bytes : %r", sb_bytes)
            else:
                raise ValidationError("Cannot download invalid base64 (.pdf) file")
            return base64.b64encode(base64.b64decode(sb_bytes)) == sb_bytes
        except Exception:
            raise ValidationError("Cannot download invalid base64 (.pdf) file")
            return False

    def generate_pdf_boleto(self):
        """
        Creates a new attachment with the Boleto PDF
        """

        # _logger.error("my acquirer_reference : %r", self.acquirer_reference)

        if self.acquirer_reference and self.pdf_boleto_id:
            return

        with ArquivoCertificado(self.acquirer_id, "w") as (key, cert):
            payment_provider = self.env['payment.acquirer'].search([('provider', '=', 'apiboletointer')])
            self.api = ApiInter(payment_provider.bank_inter_clientId, payment_provider.bank_inter_clientSecret,
                cert=(cert, key),
                conta_corrente=(
                    self.acquirer_id.journal_id.bank_account_id.acc_number
                    + self.acquirer_id.journal_id.bank_account_id.acc_number_dig
                ),
            )
            datas = self.api.boleto_pdf(self.acquirer_reference)
            if self._isBase64(datas):
                self.pdf_boleto_id = self.env["ir.attachment"].create(
                    {
                        # "res_model": "payment.transaction",
                        "name": ("Boleto %s.pdf" % self.display_name),
                        "datas": datas,
                        "type": "binary",
                    }
                )
            else:
                raise ValidationError("Cannot download invalid base64 (.pdf) file")

    def print_pdf_boleto(self):
        """
        Generates and downloads Boletos PDFs
        :return: actions.act_url
        """

        self.generate_pdf_boleto()

        if self.acquirer_reference:
            boleto_id = self.pdf_boleto_id
            iddoboleto = boleto_id.id
            base_url = self.env["ir.config_parameter"].get_param("web.base.url")
            download_url = "/web/content/%s/%s?download=True" % (
                str(boleto_id.id),
                boleto_id.name.replace("/", "_"),
            )

            return {
                "type": "ir.actions.act_url",
                "url": str(base_url) + str(download_url),
                "target": "new",
            }

    def cron_verify_transaction(self):
        documents = self.search(
            [
                ("state", "in", ["draft", "pending"]),
            ],
            limit=50,
        )
        for doc in documents:
            try:
                doc.action_verify_transaction()
                self.env.cr.commit()
            except Exception as e:
                self.env.cr.rollback()
                _logger.exception(
                    "Payment Transaction ID {}: {}.".format(doc.id, str(e)),
                    exc_info=True,
                )

    def action_verify_transaction(self):
        if self.acquirer_id.provider != "apiboletointer":
            return
        if not self.acquirer_reference:
            raise UserError(
                "Esta transação não foi enviada a nenhum gateway de pagamento"
            )
        payment_provider = self.env['payment.acquirer'].search([('provider', '=', 'apiboletointer')]
        with ArquivoCertificado(self.acquirer_id, "w") as (key, cert):
            self.api = ApiInter(payment_provider.bank_inter_clientId, payment_provider.bank_inter_clientSecret,
                cert=(cert, key),
                conta_corrente=(
                    self.acquirer_id.journal_id.bank_account_id.acc_number
                    + self.acquirer_id.journal_id.bank_account_id.acc_number_dig
                ),
            )
            data = self.api.boleto_recupera(self.acquirer_reference)

        # EMABERTO, BAIXADO e VENCIDO e PAGO
        if "errors" in data or not data:
            raise UserError(data)
        if data["situacao"] == "EMABERTO" and self.state in ("draft"):
            self._set_transaction_pending()

        if data["situacao"] == "PAGO" and self.state not in ("done", "authorized"):
            self._set_transaction_done()
            self._post_process_after_done()
            # if self.origin_move_line_id:
            # self.origin_move_line_id._create_bank_tax_move(
            #    (data.get('taxes_paid_cents') or 0) / 100)
        # else:
        # self.iugu_status = data['status']

    def cancel_transaction_in_inter(self):
        if not self.acquirer_reference:
            raise UserError(
                "Esta transação não foi enviada a nenhum gateway de pagamento"
            )
        payment_provider = self.env['payment.acquirer'].search([('provider', '=', 'apiboletointer')])
        with ArquivoCertificado(self.acquirer_id, "w") as (key, cert):
            self.api = ApiInter(payment_provider.bank_inter_clientId, payment_provider.bank_inter_clientSecret,
                cert=(cert, key),
                conta_corrente=(
                    self.acquirer_id.journal_id.bank_account_id.acc_number
                    + self.acquirer_id.journal_id.bank_account_id.acc_number_dig
                ),
            )
            data = self.api.boleto_baixa(self.acquirer_reference, "SUBISTITUICAO")

    def action_cancel_transaction(self):
        self._set_transaction_cancel()
        if self.acquirer_id.provider == "apiboletointer":
            self.cancel_transaction_in_inter()
