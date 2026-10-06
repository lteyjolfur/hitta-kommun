from django.db import models


class Kommun(models.Model):
    """One of Sweden's 290 municipalities, keyed by its official four-digit code."""

    code = models.CharField(max_length=4, primary_key=True)
    name = models.CharField(max_length=64)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.code} {self.name}"


class Indicator(models.Model):
    """A measurable property of a kommun, e.g. reported violent crimes per 1,000."""

    slug = models.SlugField(primary_key=True)
    name = models.CharField(max_length=128)
    unit = models.CharField(max_length=64)
    year = models.PositiveIntegerField()
    # True when a lower value is what most people would prefer (crime, prices).
    lower_is_better = models.BooleanField()
    source = models.CharField(max_length=255)
    source_url = models.URLField(blank=True)
    position = models.PositiveIntegerField(default=0)  # order in data/indicators.json

    class Meta:
        ordering = ["position"]

    def __str__(self):
        return self.name


class Value(models.Model):
    kommun = models.ForeignKey(Kommun, on_delete=models.CASCADE, related_name="values")
    indicator = models.ForeignKey(Indicator, on_delete=models.CASCADE, related_name="values")
    value = models.FloatField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["kommun", "indicator"], name="one_value_per_kommun_indicator"),
        ]

    def __str__(self):
        return f"{self.kommun_id} {self.indicator_id}={self.value}"
