from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("responses", "0001_initial"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="surveyresponse",
            name="survey_resp_survey__82895a_idx",
        ),
        migrations.AlterUniqueTogether(
            name="surveyresponse",
            unique_together={("survey", "user")},
        ),
    ]
