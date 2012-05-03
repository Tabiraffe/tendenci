import os
from django.forms.models import model_to_dict
from django.db.models.fields.related import ManyToManyField
from django.db.models import ForeignKey
from celery.task import Task
from celery.registry import tasks
from imports.utils import render_excel

class TendenciExportTask(Task):
    """Export Task for Celery
    This exports the entire queryset of a given TendenciBaseModel.
    """
    
    def run(self, model, fields, file_name, **kwargs):
        """Create the xls file"""
        items = model.objects.filter(status=1)
        data_row_list = []
        for item in items:
            # get the available fields from the model's meta
            opts = item._meta
            d = {}
            for f in opts.fields + opts.many_to_many:
                if f.name in fields: # include specified fields only
                    if isinstance(f, ManyToManyField):
                        value = ["%s" % obj for obj in f.value_from_object(item)]
                    if isinstance(f, ForeignKey):
                        value = getattr(item, f.name)
                    else:
                        value = f.value_from_object(item)
                    d[f.name] = value
            
            # append the accumulated values as a data row
            # keep in mind the ordering of the fields
            data_row = []
            for field in fields:
                # clean the derived values into unicode
                value = unicode(d[field]).replace(os.linesep, ' ').rstrip()
                data_row.append(value)
            
            data_row.append('\n') # append a new line to make a new row
            data_row_list.append(data_row)
        
        fields.append('\n') # append a new line to mark new row
        return render_excel(file_name, fields, data_row_list)
