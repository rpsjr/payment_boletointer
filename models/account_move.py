# © 2019 Danimar Ribeiro
# Part of OdooNext. See LICENSE file for full copyright and licensing details.

import re
import iugu
from datetime import date, timedelta
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo import api, SUPERUSER_ID, _
from odoo import registry as registry_get

import logging
from .arquivo_certificado import ArquivoCertificado

_logger = logging.getLogger(__name__)

try:
    from erpbrasil.bank.inter.boleto import BoletoInter
    from erpbrasil.bank.inter.api import ApiInter
except ImportError:
    _logger.error("Biblioteca erpbrasil.bank.inter não instalada")

try:
    from febraban.cnab240.user import User, UserAddress, UserBank
except ImportError:
    _logger.error("Biblioteca febraban não instalada")

try:
    from erpbrasil.base import misc
except ImportError:
    _logger.error("Biblioteca erpbrasil.base não instalada")


class AccountMove(models.Model):
    _inherit = 'account.move'

    @api.depends('line_ids')
    def _compute_receivables(self):
        for move in self:
            move.receivable_move_line_ids = move.line_ids.filtered(
                lambda m: m.account_id.user_type_id.type == 'receivable'
            ).sorted(key=lambda m: m.date_maturity)

    @api.depends('line_ids')
    def _compute_payables(self):
        for move in self:
            move.payable_move_line_ids = move.line_ids.filtered(
                lambda m: m.account_id.user_type_id.type == 'payable')

    receivable_move_line_ids = fields.Many2many(
        'account.move.line', string='Receivable Move Lines',
        compute='_compute_receivables')

    payable_move_line_ids = fields.Many2many(
        'account.move.line', string='Payable Move Lines',
        compute='_compute_payables')

    payment_journal_id = fields.Many2one(
        'account.journal', string='Forma de pagamento')

    def validate_data_iugu(self):
        errors = []
        for invoice in self:
            #if not invoice.payment_journal_id.receive_by_iugu:
            if not invoice.payment_mode_id.display_name == 'BOLETO INTER':
                continue
            partner = invoice.partner_id.commercial_partner_id
            #if not self.env.company.iugu_api_token:
            #if not self.payment_mode_id.fixed_journal_id.bank_inter_cert:
            #    errors.append('Configure o certificado de API')
            #if not self.payment_mode_id.fixed_journal_id.bank_inter_key:
            #    errors.append('Configure a chave de API')
            if partner.is_company and not partner.l10n_br_legal_name:
                errors.append('Destinatário - Razão Social')
            if not partner.street:
                errors.append('Destinatário / Endereço - Rua')
            if not partner.l10n_br_number:
                errors.append('Destinatário / Endereço - Número')
            if not partner.zip or len(re.sub(r"\D", "", partner.zip)) != 8:
                errors.append('Destinatário / Endereço - CEP')
            if not partner.state_id:
                errors.append(u'Destinatário / Endereço - Estado')
            if not partner.city_id:
                errors.append(u'Destinatário / Endereço - Município')
            if not partner.country_id:
                errors.append(u'Destinatário / Endereço - País')
        if len(errors) > 0:
            msg = "\n".join(
                ["Por favor corrija os erros antes de prosseguir"] + errors)
            raise ValidationError(msg)

    def send_information_to_iugu(self):
        if not self.payment_journal_id.receive_by_boletointer:
        #if not self.payment_mode_id.display_name == 'BOLETO INTER':
            return

        for moveline in self.receivable_move_line_ids:
            #self.partner_id.action_synchronize_iugu()

            #iugu_p = self.env['payment.acquirer'].search([('provider', '=', 'iugu')])
            #_acquirer = self.env['payment.acquirer'].search([('provider', '=', 'transfer')])
            payment_provider = self.env['payment.acquirer'].search([('provider', '=', 'apiboletointer')])
            transaction = self.env['payment.transaction'].sudo().create({
                'acquirer_id': payment_provider.id,
                'amount': moveline.amount_residual,
                'currency_id': moveline.move_id.currency_id.id,
                'partner_id': moveline.partner_id.id,
                'type': 'server2server',
                'date_maturity': moveline.date_maturity,
                'origin_move_line_id': moveline.id,
                'invoice_ids': [(6, 0, self.ids)]
            })
            #raise UserError(transaction)
            vals = {
                'email': self.partner_id.email,
                'due_date': moveline.date_maturity.strftime('%Y-%m-%d'),
                'ensure_workday_due_date': True,
                'items': [{
                    'description': 'Fatura Ref: %s' % moveline.name,
                    'quantity': 1,
                    'price_cents': int(moveline.amount_residual * 100),
                }],
                #'return_url': '%s/my/invoices/%s' % (base_url, self.id),
                #'notification_url': '%s/iugu/webhook?id=%s' % (base_url, self.id),
                'fines': True,
                'late_payment_fine': 2,
                'per_day_interest': True,
                'customer_id': self.partner_id,
                'early_payment_discount': False,
                'order_id': transaction.reference,
            }
            #data = iugu_invoice_api.create(vals)
            #data = None
            #if not data:
            #    data = {}
            #    data['nossoNumero'] = 123
            #    data['linhaDigitavel'] = 12345
            data = self._generate_bank_inter_boleto(moveline)

            #catch error to-do
            #if "errors" in data:
            if 0:
                if isinstance(data['errors'], str):
                    raise UserError('Erro na integração com IUGU:\n%s' % data['errors'])

                msg = "\n".join(
                    ["A integração com IUGU retornou os seguintes erros"] +
                    ["Field: %s %s" % (x[0], x[1][0])
                        for x in data['errors'].items()])
                raise UserError(msg)

            transaction.write({
                #'acquirer_reference': data['id'],
                'acquirer_reference': data['nossoNumero'] or '',
                #'transaction_url': data['secure_url'],
            })
            #transaction._set_transaction_pending()
            moveline.write({
                #'iugu_id': data['nossoNumero'] or '',
                #'iugu_secure_payment_url': data['secure_url'],
                'boleto_digitable_line': data['linhaDigitavel'] or '',
                #'iugu_barcode_url': data['bank_slip']['barcode'],
                #'transaction_ids': transaction.id,
            })
            self.transaction_ids = [(6, 0, [transaction.id])]

        ###

    def generate_payment_transactions(self):
        self.ensure_one()
        for item in self:
            item.send_information_to_iugu()

    def action_post(self):
        self.validate_data_iugu()
        result = super(AccountMove, self).action_post()
        self.generate_payment_transactions()
        #raise ValidationError('interrupção antes do post')
        return result

    #################  inter methods ###########

    def _generate_bank_inter_boleto_data(self, moveline):

        dados = []
        myself = User(
            name=self.company_id.l10n_br_legal_name,
            identifier=misc.punctuation_rm(self.company_id.l10n_br_cnpj_cpf),
            bank=UserBank(
                bankId=self.payment_mode_id.fixed_journal_id.bank_id.code_bc,
                branchCode=self.payment_mode_id.fixed_journal_id.bank_account_id.bra_number,
                accountNumber=self.payment_mode_id.fixed_journal_id.bank_account_id.acc_number,
                accountVerifier=self.payment_mode_id.fixed_journal_id.bank_account_id.acc_number_dig,
                bankName=self.payment_mode_id.fixed_journal_id.bank_id.name,
            ),
        )
        #raise ValidationError(f"{self.company_id.l10n_br_legal_name} {misc.punctuation_rm(self.company_id.l10n_br_cnpj_cpf)} {self.payment_mode_id.fixed_journal_id.bank_id.code_bc} {self.payment_mode_id.fixed_journal_id.bank_account_id.bra_number} {self.payment_mode_id.fixed_journal_id.bank_account_id.acc_number} {self.payment_mode_id.fixed_journal_id.bank_account_id.acc_number_dig} {self.payment_mode_id.fixed_journal_id.bank_id.name} ")
        #for moveline in self.receivable_move_line_ids:
        #if 1:
        payer = User(
            #name=moveline.partner_id.l10n_br_legal_name,
            name=moveline.partner_id.l10n_br_legal_name or moveline.partner_id.name,
            identifier=misc.punctuation_rm(
                moveline.partner_id.l10n_br_cnpj_cpf
            ),
            email=moveline.partner_id.email or '',
            personType=(
                "FISICA" if moveline.partner_id.company_type == 'person'
                else 'JURIDICA'),
            phone=misc.punctuation_rm(
                moveline.partner_id.phone).replace(" ", "")[2:],
            address=UserAddress(
                streetLine1=moveline.partner_id.street or '',
                district=moveline.partner_id.l10n_br_district or '',
                city=moveline.partner_id.city_id.name or '',
                stateCode=moveline.partner_id.state_id.code or '',
                zipCode=misc.punctuation_rm(moveline.partner_id.zip),
                streetNumber=moveline.partner_id.l10n_br_number,
            )
        )
        #raise ValidationError(f"{moveline.partner_id.l10n_br_legal_name} {moveline.partner_id.l10n_br_cnpj_cpf} {moveline.partner_id.email} {moveline.partner_id.company_type} {moveline.partner_id.phone} {moveline.partner_id.street} {moveline.partner_id.l10n_br_district} {moveline.partner_id.city_id.name} {moveline.partner_id.state_id.code} {moveline.partner_id.zip} {moveline.partner_id.l10n_br_number} ")
        _instructions = str(self.invoice_payment_term_id.note).split('\n')
        invoice_payment_term_id = self.invoice_payment_term_id
        codigoMora = invoice_payment_term_id.interst_mode
        mora_valor = invoice_payment_term_id.interst_value if codigoMora == 'VALORDIA' else 0
        mora_taxa  = invoice_payment_term_id.interst_value if codigoMora == 'TAXAMENSAL' else 0
        data_mm = (moveline.date_maturity +  timedelta(days=1)).strftime('%Y-%m-%d') if not codigoMora == 'ISENTO' else ''
        codigoMulta = invoice_payment_term_id.fine_mode
        multa_valor = invoice_payment_term_id.fine_value if codigoMulta == 'VALORFIXO' else 0
        multa_taxa  = invoice_payment_term_id.fine_value if codigoMulta == 'PERCENTUAL' else 0
        mora = dict(
            codigoMora=codigoMora,
            valor=mora_valor,
            taxa=mora_taxa,
            data=data_mm
            )
        multa = dict(
            codigoMulta=codigoMulta,
            valor=multa_valor,
            taxa=multa_taxa,
            data=data_mm
            )

        slip = BoletoInter(
            sender=myself,
            #amount=moveline.amount_currency,
            amount=moveline.amount_residual,
            payer=payer,
            issue_date=moveline.date,
            due_date=moveline.date_maturity,
            identifier=moveline.move_name,
            mora=mora,
            multa=multa,
            #identifier='999999999999999',
            instructions=_instructions,
        )
        #raise ValidationError(f"{moveline.amount_residual} {moveline.create_date} {moveline.date} {moveline.move_name} ")
        dados.append(slip)
        return dados

    def _generate_bank_inter_boleto(self, moveline):
        payment_provider = self.env['payment.acquirer'].search([('provider', '=', 'apiboletointer')])
        with ArquivoCertificado(payment_provider, 'w') as (key, cert):
            self.api = ApiInter(

                cert=(cert, key),
                conta_corrente=(self.payment_journal_id.bank_account_id.acc_number +
                                self.payment_journal_id.bank_account_id.acc_number_dig),
                clientId=payment_provider.bank_inter_clientId,
                clientSecret=payment_provider.bank_inter_clientSecret,
            )
            data = self._generate_bank_inter_boleto_data(moveline)
            for item in data:
                print(item._emissao_data())
                resposta = self.api.boleto_inclui(item._emissao_data())
            # o pacote python tem error handle que retorna para a aplicação
        return resposta

    #def _gererate_bank_inter_api(self):
    #    """ Realiza a conexão com o a API do banco inter"""
    #    if self.payment_type == 'inbound':
    #        return self._generate_bank_inter_boleto()
    #    else:
    #        raise NotImplementedError

    #def generate_payment_file(self):
    #    self.ensure_one()
    #    if (self.payment_mode_id.fixed_journal_id.bank_account_id ==
    #            self.env.ref('l10n_br_base.res_bank_077') and
    #            self.payment_method_id.code == 'electronic'):
    #        return self._gererate_bank_inter_api()
    #    else:
    #        return super().generate_payment_file()



class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    iugu_status = fields.Char(string="Status Iugu", default='pending', copy=False)
    iugu_id = fields.Char(string="ID Iugu", size=60, copy=False)
    iugu_secure_payment_url = fields.Char(string="URL de Pagamento", size=500, copy=False)
    boleto_digitable_line = fields.Char(string="Linha Digitável", size=100, copy=False)
    iugu_barcode_url = fields.Char(string="Código de barras", size=100, copy=False)

    def _create_bank_tax_move(self, fees_amount):
        bank_taxes = fees_amount or 0

        ref = 'Taxa: %s' % self.name
        journal = self.move_id.payment_journal_id
        currency = journal.currency_id or journal.company_id.currency_id

        move = self.env['account.move'].create({
            'name': '/',
            'journal_id': journal.id,
            'company_id': journal.company_id.id,
            'date': date.today(),
            'ref': ref,
            'currency_id': currency.id,
            'type': 'entry',
        })
        aml_obj = self.env['account.move.line'].with_context(
            check_move_validity=False)
        credit_aml_dict = {
            'name': ref,
            'move_id': move.id,
            'partner_id': self.partner_id.id,
            'debit': 0.0,
            'credit': bank_taxes,
            'account_id': journal.default_debit_account_id.id,
        }
        debit_aml_dict = {
            'name': ref,
            'move_id': move.id,
            'partner_id': self.partner_id.id,
            'debit': bank_taxes,
            'credit': 0.0,
            'account_id': journal.company_id.l10n_br_bankfee_account_id.id,
        }
        aml_obj.create(credit_aml_dict)
        aml_obj.create(debit_aml_dict)
        move.post()
        return move

    def action_mark_paid_iugu(self, iugu_data):
        self.ensure_one()
        ref = 'Fatura Ref: %s' % self.name

        journal = self.move_id.payment_journal_id
        currency = journal.currency_id or journal.company_id.currency_id

        payment = self.env['account.payment'].sudo().create({
            'bank_reference': self.iugu_id,
            'communication': ref,
            'journal_id': journal.id,
            'company_id': journal.company_id.id,
            'currency_id': currency.id,
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'amount': self.amount_residual,
            'payment_date': date.today(),
            'payment_method_id': journal.inbound_payment_method_ids[0].id,
            'invoice_ids': [(4, self.move_id.id, None)]
        })
        payment.post()

        self._create_bank_tax_move(iugu_data)

    def action_notify_due_payment(self):
        if self.invoice_id:
            self.invoice_id.message_post(
                body='Notificação do IUGU: Fatura atrasada')

    def action_verify_iugu_payment(self):
        if self.iugu_id:
            token = self.env.company.iugu_api_token
            iugu.config(token=token)
            iugu_invoice_api = iugu.Invoice()

            data = iugu_invoice_api.search(self.iugu_id)
            if "errors" in data:
                raise UserError(data['errors'])
            if data.get('status', '') == 'paid' and not self.reconciled:
                self.iugu_status = data['status']
                self.action_mark_paid_iugu(data)
            else:
                self.iugu_status = data['status']
        else:
            raise UserError('Esta parcela não foi enviada ao IUGU')

    def open_wizard_change_date(self):
        return({
            'name': 'Alterar data de vencimento',
            'type': 'ir.actions.act_window',
            'res_model': 'wizard.change.iugu.invoice',
            'view_type': 'form',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_move_line_id': self.id,
            }
        })
