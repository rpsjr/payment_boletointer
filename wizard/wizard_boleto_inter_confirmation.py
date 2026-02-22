# © 2026
from odoo import models, fields, api, _

class WizardBoletoInterConfirmation(models.TransientModel):
    _name = 'wizard.boleto.inter.confirmation'
    _description = 'Confirmar ação sobre boletos ao resetar fatura'

    move_id = fields.Many2one('account.move', string='Fatura', required=True)
    action_type = fields.Selection([
        ('overwrite', 'Sobrescrever (Cancelar boleto antigo e criar um novo)'),
        ('keep_both', 'Manter ambos (Manter antigo e criar um novo)'),
        ('keep_old', 'Manter antigo (Não criar novo boleto)')
    ], string='Ação para Boletos', default='overwrite', required=True)

    def action_confirm(self):
        self.ensure_one()
        move = self.move_id

        inter_txs = move.transaction_ids.filtered(lambda t: t.acquirer_id.provider == 'apiboletointer' and t.state not in ['cancel', 'error', 'done'])

        if self.action_type == 'overwrite':
            for tx in inter_txs:
                tx.action_cancel_transaction()

        elif self.action_type == 'keep_both':
            pass

        elif self.action_type == 'keep_old':
            move.boleto_inter_skip_generation = True

        return move.with_context(skip_boleto_check=True).button_draft()
