from django.conf.urls.defaults import patterns, url

urlpatterns = patterns('tendenci.apps.profiles.views',
    url(r'^$', 'index', name="profile.index"),
    url(r'^admins/$', 'admin_list', name="profile.admins"),
    url(r'^search/$', 'search', name="profile.search"),
    url(r'^export/$', 'export', name="profile.export"),
    url(r'^export/(?P<task_id>[-\w]+)/$', 'export', name="profile.export"),
    url(r'^export/(?P<task_id>[-\w]+)/status/$', 'export_status', name="profile.export_status"),
    url(r'^export/(?P<task_id>[-\w]+)/check/$', 'export_check', name="profile.export_check"),
    url(r'^export/(?P<task_id>[-\w]+)/download/$', 'export_download', name="profile.export_download"),
    url(r'^add/$', 'add', name="profile.add"),
    url(r'^edit/(?P<id>\d+)/$', 'edit', name="profile.edit"),
    url(r'^similar/$', 'similar_profiles', name="profile.similar"),
    url(r'^merge/(?P<sid>\d+)/$', 'merge_profiles', name="profile.merge_view"),
    url(r'^merge/process/(?P<sid>\d+)/$', 'merge_process', name="profile.merge_process"),
    url(r'^edit_perms/(?P<id>\d+)/$', 'edit_user_perms', name="profile.edit_perms"),
    url(r'^avatar/(?P<id>\d+)/$', 'change_avatar', name="profile.change_avatar"),
    url(r'^delete/(?P<id>\d+)/$', 'delete', name="profile.delete"),
    url(r'^(?P<username>[+-.\w\d@\s]+)/$', 'index', name='profile'),
    url(r'^(?P<username>[+-.\w\d@\s]+)/groups/edit/$', 'user_groups_edit', name='profile.edit_groups'),
    url(r'^(?P<username>[+-.\w\d@\s]+)/groups/(?P<membership_id>\d+)/edit/$', 'user_role_edit', name='profile.edit_role'),
    url(r'^(?P<username>[+-.\w\d@\s]+)/memberships/add/$', 'user_membership_add', name='profile.add_membership'),
)
