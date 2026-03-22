# © 2019 Danimar Ribeiro
# Part of OdooNext. See LICENSE file for full copyright and licensing details.


import base64
import logging
from datetime import datetime, timedelta
import json
import re

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.exceptions import ValidationError
from time import sleep


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
    boleto_pix_code = fields.Char(string="Pix Copia e Cola", size=1024, copy=False)

    inter_status = fields.Selection([
        ('EMABERTO', 'Em Aberto (V2)'),
        ('A_RECEBER', 'A Receber'),
        ('VENCIDO', 'Vencido (V2)'),
        ('ATRASADO', 'Atrasado'),
        ('PAGO', 'Pago (V2)'),
        ('RECEBIDO', 'Recebido'),
        ('MARCADO_RECEBIDO', 'Marcado como Recebido'),
        ('FALHA_EMISSAO', 'Falha na Emissão'),
        ('EM_PROCESSAMENTO', 'Em Processamento'),
        ('PROTESTO', 'Protesto'),
        ('BAIXADO', 'Baixado'),
        ('CANCELADO', 'Cancelado'),
        ('EXPIRADO', 'Expirado'),
    ], string="Status Inter")

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
            self.api = ApiInter(
                cert=(cert, key),
                conta_corrente=(
                    self.acquirer_id.journal_id.bank_account_id.acc_number
                    + self.acquirer_id.journal_id.bank_account_id.acc_number_dig
                ),
                clientId=payment_provider.bank_inter_clientId,
                clientSecret=payment_provider.bank_inter_clientSecret,
            )
            datas = self.api.boleto_pdf(self.acquirer_reference)
            datas = json.loads(datas)
            datas = datas["pdf"]
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
            sleep(6)
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
        payment_provider = self.env['payment.acquirer'].search([('provider', '=', 'apiboletointer')])
        with ArquivoCertificado(self.acquirer_id, "w") as (key, cert):
            self.api = ApiInter(
                cert=(cert, key),
                conta_corrente=(
                    self.acquirer_id.journal_id.bank_account_id.acc_number
                    + self.acquirer_id.journal_id.bank_account_id.acc_number_dig
                ),
                clientId=payment_provider.bank_inter_clientId,
                clientSecret=payment_provider.bank_inter_clientSecret,
            )
            if re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', self.acquirer_reference):
                data = self.api.boleto_recupera(self.acquirer_reference)
            else:
                uuid = None
                if hasattr(self.api, 'boleto_consulta'):
                    try:
                        data_base = self.date_maturity or (self.create_date.date() if self.create_date else datetime.now().date())
                        data_inicial = (data_base - timedelta(days=180)).strftime("%Y-%m-%d")
                        data_final = (data_base + timedelta(days=180)).strftime("%Y-%m-%d")

                        boletos = self.api.boleto_consulta(
                            data_inicial=data_inicial,
                            data_final=data_final,
                            filtrar_data_por="VENCIMENTO",
                            nosso_numero=self.acquirer_reference
                        )
                        if isinstance(boletos, dict) and 'content' in boletos:
                            for boleto in boletos['content']:
                                if boleto.get('nossoNumero') == self.acquirer_reference:
                                    uuid = boleto.get('codigoSolicitacao')
                                    break
                    except Exception as e:
                        _logger.warning("Erro ao consultar boleto por data: %s", str(e))

                if uuid:
                    data = self.api.boleto_recupera(uuid)
                elif hasattr(self.api, '_find_uuid_from_code'):
                    try:
                        uuid = self.api._find_uuid_from_code(self.acquirer_reference)
                        if uuid:
                            data = self.api.boleto_recupera(uuid)
                        else:
                            data = self.api.boleto_recupera(self.acquirer_reference)
                    except Exception as e:
                        _logger.error("Erro ao buscar UUID pelo codigo: %s", str(e))
                        data = self.api.boleto_recupera(self.acquirer_reference)
                else:
                    data = self.api.boleto_recupera(self.acquirer_reference)

        # EMABERTO, BAIXADO e VENCIDO e PAGO
        if "errors" in data or not data:
            raise UserError(data)

        # Capture PIX data if available and missing
        pix_code = data.get('pixCopiaECola')
        if not pix_code and 'pix' in data:
            pix_code = data['pix'].get('pixCopiaECola')

        if pix_code:
            self.write({'boleto_pix_code': pix_code})
            if self.origin_move_line_id:
                self.origin_move_line_id.write({'boleto_pix_code': pix_code})

        situacao = data.get("situacao")
        if "cobranca" in data and isinstance(data["cobranca"], dict):
             situacao = data["cobranca"].get("situacao")

        self.write({'inter_status': situacao})

        if situacao in ("EMABERTO", "A_RECEBER", "ATRASADO", "EM_PROCESSAMENTO", "PROTESTO") and self.state in ("draft"):
            self._set_transaction_pending()

        if situacao in ("PAGO", "RECEBIDO", "MARCADO_RECEBIDO") and self.state not in ("done", "authorized"):
            self._set_transaction_done()
            self._post_process_after_done()
            # if self.origin_move_line_id:
            # self.origin_move_line_id._create_bank_tax_move(
            #    (data.get('taxes_paid_cents') or 0) / 100)
        # else:
        # self.iugu_status = data['status']

        if situacao == "FALHA_EMISSAO":
            self._set_transaction_error(msg="Falha na emissão do boleto Inter")

        if situacao in ("BAIXADO", "CANCELADO", "EXPIRADO"):
            self._set_transaction_cancel()

    def cancel_transaction_in_inter(self):
        if not self.acquirer_reference:
            # Em vez de bloquear levantando UserError, evitamos o deadlock nas faturas sem referência (que nunca foram pro Inter)
            return
        payment_provider = self.env['payment.acquirer'].search([('provider', '=', 'apiboletointer')])
        with ArquivoCertificado(self.acquirer_id, "w") as (key, cert):
            self.api = ApiInter(
                cert=(cert, key),
                conta_corrente=(
                    self.acquirer_id.journal_id.bank_account_id.acc_number
                    + self.acquirer_id.journal_id.bank_account_id.acc_number_dig
                ),
                clientId=payment_provider.bank_inter_clientId,
                clientSecret=payment_provider.bank_inter_clientSecret,
            )
            data = self.api.boleto_baixa(self.acquirer_reference, "SUBSTITUICAO")


    def action_cancel_transaction(self):
        self._set_transaction_cancel()
        if self.acquirer_id.provider == "apiboletointer":
            self.cancel_transaction_in_inter()

    @api.model
    def _link_orphaned_boletos_by_invoice(self):
        """ Busca na API do Banco Inter boletos não vinculados baseando-se no nome, quantia e data de vencimento """
        
        # Filtra do recordset vindo da Ação ou faz busca global
        if self:
            transactions = self.filtered(lambda t: t.acquirer_id.provider == 'apiboletointer' and not t.acquirer_reference)
        else:
            transactions = self.search([
                ('acquirer_id.provider', '=', 'apiboletointer'),
                ('acquirer_reference', 'in', [False, '']),
                ('state', 'in', ['draft', 'pending']),
            ])
        
        if not transactions:
            return

        payment_provider = self.env['payment.acquirer'].search([('provider', '=', 'apiboletointer')], limit=1)
        if not payment_provider:
            return

        with ArquivoCertificado(payment_provider, "w") as (key, cert):
            api_inter = ApiInter(
                cert=(cert, key),
                conta_corrente=(
                    payment_provider.journal_id.bank_account_id.acc_number
                    + payment_provider.journal_id.bank_account_id.acc_number_dig
                ),
                clientId=payment_provider.bank_inter_clientId,
                clientSecret=payment_provider.bank_inter_clientSecret,
            )

            for tx in transactions:
                move_name = tx.origin_move_line_id.move_name or (tx.invoice_ids and tx.invoice_ids[0].name)
                if not move_name:
                    continue
                
                data_base = tx.date_maturity or (tx.create_date.date() if tx.create_date else datetime.now().date())
                data_inicial = (data_base - timedelta(days=15)).strftime("%Y-%m-%d")
                data_final = (data_base + timedelta(days=15)).strftime("%Y-%m-%d")

                try:
                    numero_pagina = 0
                    encontrado = False

                    while not encontrado:
                        try:
                            boletos = api_inter.boleto_consulta(
                                data_inicial=data_inicial,
                                data_final=data_final,
                                filtrar_data_por="VENCIMENTO",
                                numero_pagina=numero_pagina
                            )
                        except TypeError:
                            # Se a implementação da lib não tem suporte nativo a numero_pagina no kwargs
                            boletos = api_inter.boleto_consulta(
                                data_inicial=data_inicial,
                                data_final=data_final,
                                filtrar_data_por="VENCIMENTO"
                            )
                        
                        if not isinstance(boletos, dict) or 'content' not in boletos or not boletos['content']:
                            break
                        
                        for boleto in boletos['content']:
                            # Comparamos os 3 eixos de validacao (seuNumero, valor e data de Vencimento)
                            if boleto.get('seuNumero') == move_name:
                                try:
                                    inter_val = float(boleto.get('valorNominal', 0))
                                except ValueError:
                                    inter_val = 0.0
                                    
                                vencimento = boleto.get('dataVencimento')
                                tx_amount = float(tx.amount)
                                tx_vencimento = tx.date_maturity.strftime('%Y-%m-%d') if tx.date_maturity else None
                                
                                # Fator 0.01 de tolerância flutuante
                                if abs(inter_val - tx_amount) < 0.01 and vencimento == tx_vencimento:
                                    nosso_numero = boleto.get('nossoNumero')
                                    codigo_solicitacao = boleto.get('codigoSolicitacao')
                                    acquirer_ref = nosso_numero or codigo_solicitacao
                                    
                                    if acquirer_ref:
                                        tx.write({
                                            'acquirer_reference': acquirer_ref,
                                        })
                                        encontrado = True
                                        _logger.info("Transação %s vinculada com sucesso ao Inter %s", tx.id, acquirer_ref)
                                        
                                        try:
                                            tx.action_verify_transaction()
                                        except Exception as e_verify:
                                            _logger.warning("Falha na varredura extra: %s", str(e_verify))
                                        self.env.cr.commit()
                                        break
                        
                        if encontrado:
                            break
                            
                        # Checamos se existe uma flag last na paginação
                        if boletos.get('last') is True:
                            break
                            
                        numero_pagina += 1
                    
                    if not encontrado:
                        _logger.info("Nenhum boleto encontrado batendo as três condições para a transacao Odoo %s", tx.id)

                except Exception as e:
                    _logger.error("Erro ao buscar boleto órfão %s na api_inter: %s", tx.id, str(e))
                    self.env.cr.rollback()
                    continue
