from hmx import api, models


class SaleOrder(models.Model):
    class Meta:
        name = "saleorder"

    partner = models.ForeignKey("basepartner")
    amount = models.FloatField()
    total = models.FloatField(compute="_compute_total")

    @api.depends("amount")
    def _compute_total(self):
        for record in self:
            record.total = record.amount

    def action_confirm(self):
        return True


class Partner(models.Model):
    class Meta:
        name = "basepartner"

    name = models.CharField()
