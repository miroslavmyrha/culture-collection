from django.db import models
from django.test.utils import isolate_apps

from cultures.core.checks import public_id_errors, public_id_is_unique
from cultures.core.models import PublicModel


@isolate_apps("cultures.core")
def test_public_model_keeps_a_named_unique_constraint() -> None:
    class Sample(PublicModel):
        class Meta(PublicModel.Meta):
            app_label = "core"

    names = [c.name for c in Sample._meta.constraints]
    assert names == ["core_sample_public_id_uniq"]


@isolate_apps("cultures.core")
def test_meta_without_the_base_loses_uniqueness_and_the_check_reports_it() -> None:
    class Box(PublicModel):
        label = models.CharField(max_length=20)

        class Meta:  # does not inherit PublicModel.Meta: the constraint is gone
            app_label = "core"

    errors = public_id_errors([Box])
    assert [e.id for e in errors] == ["core.E001"]
    assert "core.Box.public_id" in errors[0].msg


def test_project_models_pass_the_check() -> None:
    assert public_id_is_unique() == []
