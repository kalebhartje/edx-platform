import json
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.urlresolvers import reverse
from django.contrib.auth.models import User, Group
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.utils.translation import ugettext as _
from django_future.csrf import ensure_csrf_cookie
from mitxmako.shortcuts import render_to_response

from xmodule.modulestore import Location
from xmodule.modulestore.django import modulestore
from contentstore.utils import get_lms_link_for_item
from util.json_request import JsonResponse
from auth.authz import (
    STAFF_ROLE_NAME, INSTRUCTOR_ROLE_NAME, get_users_in_course_group_by_role,
    add_user_to_course_group, remove_user_from_course_group,
    get_course_groupname_for_role)

from .access import has_access


@login_required
@ensure_csrf_cookie
def index(request):
    """
    List all courses available to the logged in user
    """
    courses = modulestore('direct').get_items(['i4x', None, None, 'course', None])

    # filter out courses that we don't have access too
    def course_filter(course):
        return (has_access(request.user, course.location)
                # TODO remove this condition when templates purged from db
                and course.location.course != 'templates'
                and course.location.org != ''
                and course.location.course != ''
                and course.location.name != '')
    courses = filter(course_filter, courses)

    def format_course_for_view(course):
        return (
            course.display_name,
            reverse("course_index", kwargs={
                'org': course.location.org,
                'course': course.location.course,
                'name': course.location.name,
            }),
            get_lms_link_for_item(
                course.location,
                course_id=course.location.course_id,
            ),
        )

    return render_to_response('index.html', {
        'courses': [format_course_for_view(c) for c in courses],
        'user': request.user,
        'disable_course_creation': settings.MITX_FEATURES.get('DISABLE_COURSE_CREATION', False) and not request.user.is_staff
    })


@login_required
@ensure_csrf_cookie
def manage_users(request, org, course, name):
    '''
    This view will return all CMS users who are editors for the specified course
    '''
    location = Location('i4x', org, course, 'course', name)
    # check that logged in user has permissions to this item
    if not has_access(request.user, location, role=INSTRUCTOR_ROLE_NAME) and not has_access(request.user, location, role=STAFF_ROLE_NAME):
        raise PermissionDenied()

    course_module = modulestore().get_item(location)

    staff_groupname = get_course_groupname_for_role(location, "staff")
    staff_group, __ = Group.objects.get_or_create(name=staff_groupname)
    inst_groupname = get_course_groupname_for_role(location, "instructor")
    inst_group, __ = Group.objects.get_or_create(name=inst_groupname)

    return render_to_response('manage_users.html', {
        'context_course': course_module,
        'staff': staff_group.user_set.all(),
        'instructors': inst_group.user_set.all(),
        'allow_actions': has_access(request.user, location, role=INSTRUCTOR_ROLE_NAME),
    })


@login_required
@ensure_csrf_cookie
@require_http_methods(("GET", "POST", "PUT", "DELETE"))
def course_team_user(request, org, course, name, email):
    location = Location('i4x', org, course, 'course', name)
    # check that logged in user has permissions to this item
    if has_access(request.user, location, role=INSTRUCTOR_ROLE_NAME):
        # instructors have full permissions
        pass
    elif has_access(request.user, location, role=STAFF_ROLE_NAME) and email == request.user.email:
        # staff can only affect themselves
        pass
    else:
        msg = {
            "error": _("Insufficient permissions")
        }
        return JsonResponse(msg, 400)

    try:
        user = User.objects.get(email=email)
    except:
        msg = {
            "error": _("Could not find user by email address '{email}'.").format(email=email),
        }
        return JsonResponse(msg, 404)

    # role hierarchy: "instructor" has more permissions than "staff" (in a course)
    roles = ["instructor", "staff"]

    if request.method == "GET":
        # just return info about the user
        msg = {
            "email": user.email,
            "active": user.is_active,
            "role": None,
        }
        # what's the highest role that this user has?
        groupnames = set(g.name for g in user.groups.all())
        for role in roles:
            role_groupname = get_course_groupname_for_role(location, role)
            if role_groupname in groupnames:
                msg["role"] = role
                break
        return JsonResponse(msg)

    # can't modify an inactive user
    if not user.is_active:
        msg = {
            "error": _('User {email} has registered but has not yet activated his/her account.').format(email=email),
        }
        return JsonResponse(msg, 400)

    # make sure that the role groups exist
    staff_groupname = get_course_groupname_for_role(location, "staff")
    staff_group, __ = Group.objects.get_or_create(name=staff_groupname)
    inst_groupname = get_course_groupname_for_role(location, "instructor")
    inst_group, __ = Group.objects.get_or_create(name=inst_groupname)

    if request.method == "DELETE":
        # remove all roles in this course from this user: but fail if the user
        # is the last instructor in the course team
        instructors = set(inst_group.user_set.all())
        staff = set(staff_group.user_set.all())
        if user in instructors and len(instructors) == 1:
            msg = {
                "error": _("You may not remove the last instructor from a course")
            }
            return JsonResponse(msg, 400)

        if user in instructors:
            user.groups.remove(inst_group)
        if user in staff:
            user.groups.remove(staff_group)
        user.save()
        return JsonResponse()

    # all other operations require the requesting user to specify a role
    if request.META.get("CONTENT_TYPE", "") == "application/json" and request.body:
        try:
            payload = json.loads(request.body)
        except:
            return JsonResponse({"error": _("malformed JSON")}, 400)
        try:
            role = payload["role"]
        except KeyError:
            return JsonResponse({"error": _("`role` is required")}, 400)
    else:
        if not "role" in request.POST:
            return JsonResponse({"error": _("`role` is required")}, 400)
        role = request.POST["role"]

    if role == "instructor":
        if not has_access(request.user, location, role=INSTRUCTOR_ROLE_NAME):
            msg = {
                "error": _("Only instructors may create other instructors")
            }
            return JsonResponse(msg, 400)
        add_user_to_course_group(request.user, user, location, role)
    elif role == "staff":
        # if we're trying to downgrade a user from "instructor" to "staff",
        # make sure we have at least one other instructor in the course team.
        instructors = set(inst_group.user_set.all())
        if user in instructors:
            if len(instructors) == 1:
                msg = {
                    "error": _("You may not remove the last instructor from a course")
                }
                return JsonResponse(msg, 400)
            remove_user_from_course_group(request.user, user, location, "instructor")
        add_user_to_course_group(request.user, user, location, role)
    return JsonResponse()
