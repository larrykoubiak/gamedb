"""Django model stubs mapped to the existing SQLAlchemy tables."""

from django.db import models


class System(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255)

    class Meta:
        managed = False
        db_table = "systems"


class Title(models.Model):
    id = models.AutoField(primary_key=True)
    system = models.ForeignKey(System, models.DO_NOTHING, db_column="system_id")
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "titles"


class Release(models.Model):
    id = models.AutoField(primary_key=True)
    title = models.ForeignKey(Title, models.DO_NOTHING, db_column="title_id")
    region = models.CharField(max_length=255, null=True, blank=True)
    release_year = models.IntegerField(null=True, blank=True)
    release_month = models.IntegerField(null=True, blank=True)
    serial = models.CharField(max_length=255, null=True, blank=True)
    display_name = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        managed = False
        db_table = "releases"


class Rom(models.Model):
    id = models.AutoField(primary_key=True)
    release = models.ForeignKey(Release, models.DO_NOTHING, db_column="release_id")
    rom_name = models.CharField(max_length=255, null=True, blank=True)
    size = models.BigIntegerField(null=True, blank=True)
    crc = models.CharField(max_length=255, null=True, blank=True)
    md5 = models.CharField(max_length=255, null=True, blank=True)
    sha1 = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        managed = False
        db_table = "roms"


class Attribute(models.Model):
    id = models.AutoField(primary_key=True)
    entity_type = models.CharField(max_length=255)
    entity_id = models.IntegerField()
    key = models.CharField(max_length=255)
    value = models.TextField(null=True, blank=True)
    source = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        managed = False
        db_table = "attributes"
