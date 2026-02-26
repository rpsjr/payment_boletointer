# © 2018 Danimar Ribeiro, Trustcode
# Part of Trustcode. See LICENSE file for full copyright and licensing details.

import logging
from odoo import http, SUPERUSER_ID
from odoo.http import request

_logger = logging.getLogger(__name__)


class InterController(http.Controller):

    @http.route('/boleto/inter/pdf/<int:transaction_id>', type='http', auth="public", website=True)
    def boleto_inter_pdf(self, transaction_id, **kw):
        transaction = request.env['payment.transaction'].sudo().browse(transaction_id)

        if not transaction.exists() or transaction.acquirer_id.provider != 'apiboletointer':
            return request.not_found()

        try:
            transaction.generate_pdf_boleto()

            if not transaction.pdf_boleto_id:
                 return request.not_found()

            pdf_content = transaction.pdf_boleto_id.datas
            if not pdf_content:
                 return request.not_found()

            import base64
            pdf_content = base64.b64decode(pdf_content)

            headers = [
                ('Content-Type', 'application/pdf'),
                ('Content-Length', len(pdf_content)),
                ('Content-Disposition', 'attachment; filename="Boleto_Inter_%s.pdf"' % transaction.acquirer_reference)
            ]
            return request.make_response(pdf_content, headers)

        except Exception as e:
            _logger.exception("Erro ao gerar PDF do Boleto Inter via Controller")
            return request.not_found()

