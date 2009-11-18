from django.contrib.gis.db import models
from django.forms import ModelForm, ValidationError
from sorl.thumbnail.fields import ImageWithThumbnailsField 


class CommunityBoard(models.Model):
    gid = models.IntegerField(primary_key=True)
    borocd = models.IntegerField()
    name = models.CharField(max_length=10)
    the_geom = models.MultiPolygonField()
    objects = models.GeoManager()

    class Meta:
        db_table = u'gis_community_board'
        ordering = ['name']

    def __unicode__(self):
        return "Brooklyn Community Board %s " % self.name




class Rack(models.Model): 
    address = models.CharField(max_length=200)
    title = models.CharField(max_length=50)
    date = models.DateTimeField()
    description = models.CharField(max_length=300, blank=True)
    email = models.EmailField()
    photo = ImageWithThumbnailsField(
                              upload_to='images/racks/', 
                              thumbnail={'size': (100, 100)},
                              extra_thumbnails = {
                                   'large': {'size': (400,400)}, 
                                },    
                              blank=True, null=True)
    # We might make this a foreign key to a User eventually, but for now
    # it's optional.
    user = models.CharField(max_length=20, blank=True, null=True)
    location = models.PointField(srid=4326)

    verified = models.BooleanField(default=False, blank=True)

    # keep track of where the rack was submitted from
    # if not set, that means it was submitted from the web
    source = models.ForeignKey('Source', null=True)
    
    objects = models.GeoManager()

    def __unicode__(self):
        return self.address



class Source(models.Model):
    """base class representing the source of where a rack was submitted from"""

    # string based name used to identify where a source came from
    name = models.CharField(max_length=20)


class EmailSource(Source):
    address = models.EmailField()


class TwitterSource(Source):
    user = models.CharField(max_length=50)
    status_id = models.IntegerField()

    def get_absolute_url(self):
        user = self.user
        status_id = self.status_id
        return 'http://twitter.com/%(user)s/%(status_id)d' % locals()


class SeeClickFixSource(Source):
    issue_id = models.IntegerField()
    reporter = models.CharField(max_length=100)
    image_url = models.URLField()

    def get_absolute_url(self):
        return 'http://www.seeclickfix.com/issues/%d' % self.issue_id



class StatementOfSupport(models.Model): 
    file = models.FileField(upload_to='documents/', blank=True, null=True)
    email = models.EmailField()
    s_rack = models.ForeignKey(Rack)

    class Meta: 
        ordering = ['s_rack']

    def __unicode__(self):
        return self.email



class Comment(models.Model):
    text = models.CharField(max_length=300)
    email = models.EmailField()
    rack = models.ForeignKey(Rack)
    
    class Meta: 
        ordering = ['rack']

    def __unicode__(self):
        return self.email



class Neighborhoods(models.Model):
    gid = models.IntegerField(primary_key=True)
    state = models.CharField(max_length=2)
    county = models.CharField(max_length=43)
    city = models.CharField(max_length=64)
    name = models.CharField(max_length=64)
    regionid = models.IntegerField()
    the_geom = models.MultiPolygonField() 
    objects = models.GeoManager()

    class Meta:
        db_table = u'gis_neighborhoods'
        
    def __unicode__(self):
        return self.name


class SubwayStations(models.Model):
    gid = models.IntegerField(primary_key=True)
    objectid = models.TextField() # This field type is a guess.
    id = models.IntegerField()
    name = models.CharField(max_length=31)
    alt_name = models.CharField(max_length=38)
    cross_st = models.CharField(max_length=27)
    long_name = models.CharField(max_length=60)
    label = models.CharField(max_length=50)
    borough = models.CharField(max_length=15)
    nghbhd = models.CharField(max_length=30)
    routes = models.CharField(max_length=20)
    transfers = models.CharField(max_length=25)
    color = models.CharField(max_length=30)
    express = models.CharField(max_length=10)
    closed = models.CharField(max_length=10)
    the_geom = models.PointField()
    objects = models.GeoManager()
    class Meta:
        db_table = u'gis_subway_stations'




class RackForm(ModelForm): 
    class Meta: 
        model = Rack

    def clean_verified(self):
        verified = self.cleaned_data.get('verified')
        errors = []
        if verified:
            if not (self.cleaned_data.get('photo') or (
                self.is_bound and bool(self.instance.photo))):
                errors.append(
                    "You can't mark a rack as verified unless it"
                    " has a photo")
            if errors:
                raise ValidationError(errors)
        return verified

class CommentForm(ModelForm): 
    class Meta: 
        model = Comment
        

class SupportForm(ModelForm): 
    class Meta: 
        model = StatementOfSupport
