from odoo import api, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        Employee = self.env['hr.employee'].sudo()
        for user in users:
            if user.share:
                continue
            if Employee.search_count([('user_id', '=', user.id)]):
                continue
            Employee.create({
                'name': user.name,
                'user_id': user.id,
                'work_email': user.login,
                'company_id': user.company_id.id,
            })
        return users
