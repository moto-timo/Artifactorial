# -*- coding: utf-8 -*-
# vim: set ts=4

from django.db.models import Q
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.core.servers.basehttp import FileWrapper
from django.forms import ModelForm
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render_to_response
from django.template import RequestContext
from django.views.decorators.csrf import csrf_exempt

from Artifactorial.models import AuthToken, Artifact, Directory

import os
import urllib


def index(request):
    artifacts = Artifact.objects.all()

    return render_to_response('Artifactorial/index.html',
                              {'artifacts': artifacts},
                              context_instance=RequestContext(request))


class ArtifactForm(ModelForm):
    class Meta:
        model = Artifact
        fields = ('path', 'directory', 'is_permanent')


@csrf_exempt
def post(request):
    if request.method == 'POST':
        # Find the directory by name
        directory_path = request.POST.get('directory', '')
        directory = get_object_or_404(Directory, path=directory_path)
        request.POST['directory'] = directory.id

        # Is the directory private ?
        if not directory.is_anonymous():
            # Get the current token
            try:
                token = AuthToken.objects.get(secret=request.POST.get('token', ''),
                                              user__username=request.POST.get('user', ''))
            except AuthToken.DoesNotExist:
                raise PermissionDenied

            # The directory belongs to a user ...
            if directory.user:
                if directory.user.id != token.user.id:
                    raise PermissionDenied
            # ... or a group
            else:
                if directory.group not in token.user.groups.all():
                    raise PermissionDenied

        # Validate the updated form
        form = ArtifactForm(request.POST, request.FILES)
        if form.is_valid():
            artifact = form.save()
            return HttpResponse(artifact.path.url, content_type='text/plain')
        else:
            raise PermissionDenied
    else:
        raise PermissionDenied


def get_current_user(request):
    try:
        token = AuthToken.objects.get(secret=request.GET.get('token', ''),
                                      user__username=request.GET.get('user', ''))
        return token.user
    except AuthToken.DoesNotExist:
        return request.user


def get(request, filename):
    # Get the current user
    user = get_current_user(request)

    # TODO: only show the authorized elements
    # Is it a file or a path
    if filename[-1] == '/':
        dirname = os.path.dirname(filename)

        dirname_length = len(dirname)
        # Special case for the root directory
        if dirname == '/':
            dirname_length = 0

        dir_set = set()
        art_list = list()

        # List real directories
        directories = Directory.objects.filter(Q(path__startswith="%s" % (dirname)) | Q(path=dirname))
        for directory in directories:
            if not directory.is_visible_to(user):
                continue
            if directory.path != dirname:
                # Sub directory => print the next elements in the path
                full_dir_name = directory.path[dirname_length+1:]
                try:
                    index = full_dir_name.index('/')
                    dir_set.add(full_dir_name[:index])
                except Exception:
                    dir_set.add(full_dir_name)

        # List artifacts and pseudo directories
        artifacts = Artifact.objects.filter(path__startswith=filename.lstrip('/'))
        for artifact in artifacts:
            if not artifact.is_visible_to(user):
                continue
            relative_name = artifact.path.name[dirname_length:]
            # Add pseudo directory (if the name contains a '/')
            try:
                index = relative_name.index('/')
                dir_set.add(relative_name[:index])
            except Exception:
                art_list.append((artifact.path.name[dirname_length:],
                                 artifact.path.size))

        return render_to_response('Artifactorial/list.html',
                                  {'directory': dirname,
                                   'directories': dir_set,
                                   'files': art_list},
                                  context_instance=RequestContext(request))
    else:
        # Serving the file
        # TODO: use django-sendfile for more performances
        # TODO: find the right mime-type to return
        artifact = get_object_or_404(Artifact, path=filename.lstrip('/'))
        if not artifact.is_visible_to(user):
            raise PermissionDenied

        artifact_filename = urllib.quote(artifact.path.name.split('/')[-1])
        wrapper = FileWrapper(artifact.path.file)
        response = HttpResponse(wrapper, content_type='text/plain')
        response['Content-Disposition'] = 'attachment; filename=%s' % artifact_filename
        response['Content-Length'] = artifact.path.size
        return response
