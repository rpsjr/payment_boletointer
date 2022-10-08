# Copyright 2020 KMEE
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models


class AccountJournal(models.Model):

    _inherit = 'account.journal'

    receive_by_boletointer = fields.Boolean(string="Cobrança Banco Inter?")

    bank_inter_cert = fields.Binary(string='Bank Inter Certificate')

    bank_inter_key = fields.Binary(string='Bank Inter Key')

    bank_inter_clientId = fields.Binary(string='Bank Inter ClientId')

    bank_inter_clientSecret = fields.Binary(string='Bank Inter ClientSecret')
