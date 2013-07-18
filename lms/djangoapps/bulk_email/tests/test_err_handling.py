"""
Unit tests for handling email sending errors
"""

from django.test.utils import override_settings
from django.core.urlresolvers import reverse
from courseware.tests.tests import TEST_DATA_MONGO_MODULESTORE
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase
from xmodule.modulestore.tests.factories import CourseFactory
from student.tests.factories import UserFactory, AdminFactory, CourseEnrollmentFactory
from smtp_server_thread import FakeSMTPServerThread

from mock import patch
from smtplib import SMTPDataError, SMTPServerDisconnected, SMTPConnectError

TEST_SMTP_PORT = 1025

@override_settings(MODULESTORE=TEST_DATA_MONGO_MODULESTORE, EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend', EMAIL_HOST='localhost', EMAIL_PORT=TEST_SMTP_PORT)
class TestEmailErrors(ModuleStoreTestCase):
    def setUp(self):
        self.course = CourseFactory.create()
        instructor = AdminFactory.create()
        self.client.login(username=instructor.username, password="test")

        self.smtp_server_thread = FakeSMTPServerThread('localhost', TEST_SMTP_PORT)
        self.smtp_server_thread.start()

    def tearDown(self):
        self.smtp_server_thread.stop()

    @patch('bulk_email.tasks.course_email.retry')
    def test_data_err_retry(self, retry):
        """
        Test that celery handles transient SMTPDataErrors by retrying
        """
        self.smtp_server_thread.server.set_errtype("DATA", "454 Throttling failure: Daily message quota exceeded.")
        url = reverse('instructor_dashboard', kwargs={'course_id': self.course.id})
        response = self.client.post(url, {'action': 'Send email', 'to': 'myself', 'subject': 'test subject for myself', 'message': 'test message for myself'})
        self.assertTrue(retry.called)
        (_,kwargs) = retry.call_args
        exc = kwargs['exc']
        self.assertTrue(type(exc) == SMTPDataError)

    @patch('bulk_email.tasks.course_email_result')
    @patch('bulk_email.tasks.course_email.retry')
    def test_data_err_fail(self, retry, result):
        """
        Test that celery handles permanent SMTPDataErrors by failing and not retrying
        """
        self.smtp_server_thread.server.set_errtype("DATA", "554 Message rejected: Email address is not verified.")
        self.students = [UserFactory() for _ in xrange(10)]
        for student in self.students:
            CourseEnrollmentFactory.create(user=student, course_id=self.course.id)

        url = reverse('instructor_dashboard', kwargs={'course_id': self.course.id})
        response = self.client.post(url, {'action': 'Send email', 'to': 'all', 'subject': 'test subject for all', 'message': 'test message for all'})
        self.assertFalse(retry.called)

        #test that after the failed email, the rest send successfully
        ((sent, fail),_) = result.call_args
        self.assertEquals(fail, 1)
        self.assertEquals(sent, 9)

    @patch('bulk_email.tasks.course_email.retry')
    def test_disconn_err_retry(self, retry):
        """
        Test that celery handles SMTPServerDisconnected by retrying
        """
        self.smtp_server_thread.server.set_errtype("DISCONN", "Server disconnected, please try again later.")
        url = reverse('instructor_dashboard', kwargs={'course_id': self.course.id})
        response = self.client.post(url, {'action': 'Send email', 'to': 'myself', 'subject': 'test subject for myself', 'message': 'test message for myself'})
        self.assertTrue(retry.called)
        (_,kwargs) = retry.call_args
        exc = kwargs['exc']
        self.assertTrue(type(exc) == SMTPServerDisconnected)

    @patch('bulk_email.tasks.course_email.retry')
    def test_conn_err_retry(self, retry):
        """
        Test that celery handles SMTPConnectError by retrying
        """
        #SMTP reply is already specified in fake SMTP Channel created
        self.smtp_server_thread.server.set_errtype("CONN")
        url = reverse('instructor_dashboard', kwargs={'course_id': self.course.id})
        response = self.client.post(url, {'action': 'Send email', 'to': 'myself', 'subject': 'test subject for myself', 'message': 'test message for myself'})
        self.assertTrue(retry.called)
        (_,kwargs) = retry.call_args
        exc = kwargs['exc']
        self.assertTrue(type(exc) == SMTPConnectError)