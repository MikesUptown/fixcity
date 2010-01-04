'''
This is a manage.py command for django which handles incoming email,
typically via stdin.

To hook this up with postfix, set up an alias along the lines of:

myaddress: "|PYTHON_EGG_CACHE=/tmp/my-egg-cache /PATH/TO/VENV/bin/python /PATH/TO/VENV/src/fixcity/fixcity/manage.py handle_mailin -u http://MYDOMAIN/racks/ --debug=9 - >> /var/log/MYLOGS/mailin.log 2>&1""
'''

# based on email2trac.py, which is Copyright (C) 2002 under the GPL v2 or later

from datetime import datetime
from optparse import make_option
from poster.encode import multipart_encode
from stat import S_IRWXU, S_IRWXG, S_IRWXO
import email.Header
import httplib2
import mimetypes
import os
import re
import socket
import string
import sys
import tempfile
import time
import traceback
import unicodedata
import urlparse

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import simplejson as json

from django.conf import settings

class EmailParser(object):

    msg = None
    
    def __init__(self, parameters):

        # Save parameters
        #
        self.parameters = parameters

        # Some useful mail constants
        #
        self.author = None
        self.email_addr = None
        self.email_from = None
        self.id = None

        # XXX Cull stuff that just stores a value, we should just
        # store all the parameters instead.
        if parameters.has_key('debug'):
            self.DEBUG = int(parameters['debug'])
        else:
            self.DEBUG = 0

        if parameters.has_key('email_quote'):
            self.EMAIL_QUOTE = str(parameters['email_quote'])
        else:
            self.EMAIL_QUOTE = '> '

        if parameters.has_key('email_header'):
            self.EMAIL_HEADER = int(parameters['email_header'])
        else:
            self.EMAIL_HEADER = 0

        if parameters.has_key('reply_all'):
            self.REPLY_ALL = int(parameters['reply_all'])
        else:
            self.REPLY_ALL = 0

        if parameters.has_key('rack_update'):
            self.RACK_UPDATE = int(parameters['rack_update'])
        else:
            self.RACK_UPDATE = 0

        if parameters.has_key('drop_alternative_html_version'):
            self.DROP_ALTERNATIVE_HTML_VERSION = int(parameters['drop_alternative_html_version'])
        else:
            self.DROP_ALTERNATIVE_HTML_VERSION = 0

        if parameters.has_key('strip_signature'):
            self.STRIP_SIGNATURE = int(parameters['strip_signature'])
        else:
            self.STRIP_SIGNATURE = 0

        if parameters.has_key('binhex'):
            self.BINHEX = parameters['binhex']
        else:
            self.BINHEX = 'warn'

        if parameters.has_key('applesingle'):
            self.APPLESINGLE = parameters['applesingle']
        else:
            self.APPLESINGLE = 'warn'

        if parameters.has_key('appledouble'):
            self.APPLEDOUBLE = parameters['appledouble']
        else:
            self.APPLEDOUBLE = 'warn'

        self.MAX_ATTACHMENT_SIZE = int(parameters.get('max-attachment-size', -1))


    def email_to_unicode(self, message_str):
        """
        Email has 7 bit ASCII code, convert it to unicode with the charset
that is encoded in 7-bit ASCII code and encode it as utf-8.
        """
        results =  email.Header.decode_header(message_str)
        str = None
        for text,format in results:
            if format:
                try:
                    temp = unicode(text, format)
                except UnicodeError, detail:
                    # This always works
                    #
                    temp = unicode(text, 'iso-8859-15')
                except LookupError, detail:
                    #text = 'ERROR: Could not find charset: %s, please install' %format
                    #temp = unicode(text, 'iso-8859-15')
                    temp = message_str

            else:
                temp = string.strip(text)
                temp = unicode(text, 'iso-8859-15')

            if str:
                str = '%s %s' %(str, temp)
            else:
                str = '%s' %temp

        #str = str.encode('utf-8')
        return str

    def debug_body(self, message_body):
        body_file = tempfile.mktemp('.handle_mailin')

        print 'TD: writing body (%s)' % body_file
        fx = open(body_file, 'wb')
        if not message_body:
            message_body = '(None)'

        message_body = message_body.encode('utf-8')
        #message_body = unicode(message_body, 'iso-8859-15')

        fx.write(message_body)
        fx.close()
        try:
            os.chmod(body_file,S_IRWXU|S_IRWXG|S_IRWXO)
        except OSError:
            pass

    def debug_attachments(self, message_parts):
        n = 0
        for part in message_parts:
            # Skip inline text parts
            if not isinstance(part, tuple):
                continue

            (original, filename, part) = part

            n = n + 1
            print 'TD: part%d: Content-Type: %s' % (n, part.get_content_type())
            print 'TD: part%d: filename: %s' % (n, part.get_filename())

            part_file = tempfile.mktemp('.handle_mailin.part%d' % n)

            print 'TD: writing part%d (%s)' % (n,part_file)
            fx = open(part_file, 'wb')
            text = part.get_payload(decode=1)
            if not text:
                text = '(None)'
            fx.write(text)
            fx.close()
            try:
                os.chmod(part_file,S_IRWXU|S_IRWXG|S_IRWXO)
            except OSError:
                pass


    def get_sender_info(self):
        """
        Get the default author name and email address from the message
        """
        message = self.msg
        self.email_to = self.email_to_unicode(message['to'])
        self.to_name, self.to_email_addr = email.Utils.parseaddr (self.email_to)

        self.email_from = self.email_to_unicode(message['from'])
        self.author, self.email_addr  = email.Utils.parseaddr(self.email_from)

        # Trac can not handle author's name that contains spaces
        # XXX do we care about author's name for fixcity? prob not.
        self.author = self.email_addr



    def save_email_for_debug(self, message):
        msg_file = tempfile.mktemp('.email2trac')
 
        print 'TD: saving email to %s' % msg_file
        fx = open(msg_file, 'wb')
        fx.write('%s' % message)
        fx.close()
        try:
            os.chmod(msg_file,S_IRWXU|S_IRWXG|S_IRWXO)
        except OSError:
            pass


    def new_rack(self, title, address, spam):
        """
        Create a new rack
        """
        msg = self.msg
        if self.DEBUG:
            print "TD: new_rack"

        message_parts = self.get_message_parts()
        message_parts = self.unique_attachment_names(message_parts)

        description = self.description = self.body_text(message_parts)
        photos = self.get_photos(message_parts)
        # We don't bother with microsecond precision because
        # Django datetime fields can't parse it anyway.
        now = datetime.fromtimestamp(int(time.time()))
        data = dict(title=title,
                    source_type='email',
                    description=description,
                    date=now.isoformat(' '),
                    address=address,
                    geocoded=0,  # Do server-side location processing.
                    got_communityboard=0,   # Ditto.
                    email=self.email_addr,
                    )
        
        if self.parameters.get('dry-run') and self.DEBUG:
            print "TD: would save rack here"
            return

        # This is the one thing i apparently can't do
        # when running as `nobody`.
        # And getting postfix to run this script as another user
        # seems to be a PITA.
        #rack = rackform.save()

        # So instead, let's POST our data to some URL...
        url = self.parameters['url']
        jsondata = json.dumps(data)
        http = httplib2.Http()
        headers = {'Content-type': 'application/json'}
        error_subject = "Unsuccessful Rack Request"
        try:
            response, content = http.request(url, 'POST',
                                             headers=headers,
                                             body=jsondata)
        except socket.error:
            self.bounce(
                error_subject,
                "Thanks for trying to suggest a rack.\n"
                "We are unfortunately experiencing some difficulties at the\n"
                "moment -- please try again in an hour or two!",
                notify_admin='Server down??'
                )
            return

        if self.DEBUG:
            print "TD: server responded with:\n%s" % content

        if response.status >= 500:
            err_msg = (
                "Thanks for trying to suggest a rack.\n"
                "We are unfortunately experiencing some difficulties at the\n"
                "moment. Please check to make sure your subject line follows\n"
                "this format exactly:\n\n"
                "  Key Foods @224 McGuinness Blvd Brooklyn NY\n\n"
                "If you've made an error, please resubmit. Otherwise we'll\n"
                "look into this issue and get back to you as soon as we can.\n"
                )
            admin_body = content
            self.bounce(error_subject, err_msg, notify_admin='500 Server error',
                        notify_admin_body=content)
            return

        result = json.loads(content)
        if result.has_key('errors'):

            err_msg = (
                "Thanks for trying to suggest a rack through fixcity.org,\n"
                "but it won't go through without the proper information.\n\n"
                "Please correct the following errors:\n\n")

            errors = adapt_errors(result['errors'])
            for k, v in sorted(errors.items()):
                err_msg += "%s: %s\n" % (k, '; '.join(v))

            err_msg += "\nPlease try again!\n"
            self.bounce(error_subject, err_msg)
            return

        parsed_url = urlparse.urlparse(url)
        base_url = parsed_url[0] + '://' + parsed_url[1]
        photo_url = base_url + result['photo_post_url']
        rack_url = base_url + result['rack_url']
        rack_user = result.get('user')

        if photos.has_key('photo'):
            datagen, headers = multipart_encode({'photo':
                                                 photos['photo']})
            # httplib2 doesn't like poster's integer headers.
            headers['Content-Length'] = str(headers['Content-Length'])
            body = ''.join([s for s in datagen])
            response, content = http.request(photo_url, 'POST',
                                             headers=headers, body=body)
            # XXX handle errors
            if self.DEBUG:
                print "TD: result from photo upload:"
                print content
        # XXX need to add links per
        # https://projects.openplans.org/fixcity/wiki/EmailText
        # ... will need an HTML version.
        reply = "Thanks for your rack suggestion!\n\n"
        reply += "You must verify that your spot meets DOT requirements\n"
        reply += "before we can submit it.\n"
        reply += "To verify, go to: %(rack_url)sedit/\n\n"
        if not rack_user:
            # XXX Create an inactive account and add a confirmation link.
            reply += "To create an account, go to %(base_url)s/accounts/register/ .\n\n"  % locals()
        reply += "Thanks!\n\n"
        reply += "- The Open Planning Project & Livable Streets Initiative\n"
        reply = reply % locals()
        self.reply("FixCity Rack Confirmation", reply)


    def parse(self, s):
        self.msg = email.message_from_string(s)
        if not self.msg:
            if self.DEBUG:
                print "TD: This is not a valid email message format"
            return

        # Work around lack of header folding in Python; see http://bugs.python.org/issue4696
        self.msg.replace_header('Subject', self.msg['Subject'].replace('\r', '').replace('\n', ''))

        message_parts = self.get_message_parts()
        message_parts = self.unique_attachment_names(message_parts)
        body_text = self.body_text(message_parts)

        if self.DEBUG > 1:        # save the entire e-mail message text
            self.save_email_for_debug(self.msg)
            self.debug_body(body_text)
            self.debug_attachments(message_parts)

        self.get_sender_info()
        subject  = self.email_to_unicode(self.msg.get('Subject', ''))

        spam_msg = False #XXX not sure what this should be

        subject_re = re.compile(r'(?P<title>[^\@]*)\s*@(?P<address>.*)')
        subject_match = subject_re.search(subject)
        if subject_match:
            title = subject_match.group('title').strip()
            address = subject_match.group('address')
        else:
            address_re = re.compile(r'@(?P<address>.+)$', re.MULTILINE)
            address_match = address_re.search(body_text)
            if address_match:
                address = address_match.group('address')
            else:
                address = ''  # Let the server deal with lack of address.
            title = subject

        address = address.strip()
        self.new_rack(title, address, spam_msg)
            
    def strip_signature(self, text):
        """
        Strip signature from message, inspired by Mailman software
        """
        body = []
        for line in text.splitlines():
            if line == '-- ':
                break
            body.append(line)

        return ('\n'.join(body))


    def get_message_parts(self):
        """
        parses the email message and returns a list of body parts and attachments
        body parts are returned as strings, attachments are returned as tuples of (filename, Message object)
        """
        msg = self.msg
        message_parts = []

        # This is used to figure out when we are inside an AppleDouble container
        # AppleDouble containers consists of two parts: Mac-specific file data, and platform-independent data
        # We strip away Mac-specific stuff
        appledouble_parts = []

        ALTERNATIVE_MULTIPART = False

        for part in msg.walk():
            if self.DEBUG:
                print 'TD: Message part: Main-Type: %s' % part.get_content_maintype()
                print 'TD: Message part: Content-Type: %s' % part.get_content_type()


            # Check whether we just finished processing an AppleDouble container
            if part not in appledouble_parts:
                appledouble_parts = []

            ## Check content type
            #
            if part.get_content_type() == 'application/mac-binhex40':
                #
                # Special handling for BinHex attachments. Options are drop (leave out with no warning), warn (and leave out), and keep
                #
                if self.BINHEX == 'warn':
                    message_parts.append("'''A BinHex attachment named '%s' was ignored (use MIME encoding instead).'''" % part.get_filename())
                    continue
                elif self.BINHEX == 'drop':
                    continue

            elif part.get_content_type() == 'application/applefile':
                #
                # Special handling for the Mac-specific part of AppleDouble/AppleSingle attachments. Options are strip (leave out with no warning), warn (and leave out), and keep
                #

                if part in appledouble_parts:
                    if self.APPLEDOUBLE == 'warn':
                        message_parts.append("'''The resource fork of an attachment named '%s' was removed.'''" % part.get_filename())
                        continue
                    elif self.APPLEDOUBLE == 'strip':
                        continue
                else:
                    if self.APPLESINGLE == 'warn':
                        message_parts.append("'''An AppleSingle attachment named '%s' was ignored (use MIME encoding instead).'''" % part.get_filename())
                        continue
                    elif self.APPLESINGLE == 'drop':
                        continue

            elif part.get_content_type() == 'multipart/appledouble':
                #
                # If we entering an AppleDouble container, set up appledouble_parts so that we know what to do with its subparts
                #
                appledouble_parts = part.get_payload()
                continue

            elif part.get_content_type() == 'multipart/alternative':
                ALTERNATIVE_MULTIPART = True
                continue

            # Skip multipart containers
            #
            if part.get_content_maintype() == 'multipart':
                if self.DEBUG:
                    print "TD: Skipping multipart container"
                continue

            # Check if this is an inline part. It's inline if there is co Cont-Disp header, or if there is one and it says "inline"
            inline = self.inline_part(part)

            # Drop HTML message
            if ALTERNATIVE_MULTIPART and self.DROP_ALTERNATIVE_HTML_VERSION:
                if part.get_content_type() == 'text/html':
                    if self.DEBUG:
                        print "TD: Skipping alternative HTML message"

                    ALTERNATIVE_MULTIPART = False
                    continue

            # Inline text parts are where the body is
            if part.get_content_type() == 'text/plain' and inline:
                if self.DEBUG:
                    print 'TD:               Inline body part'

                # Try to decode, if fails then do not decode
                #
                body_text = part.get_payload(decode=1)
                if not body_text:
                    body_text = part.get_payload(decode=0)

                format = email.Utils.collapse_rfc2231_value(part.get_param('Format', 'fixed')).lower()
                delsp = email.Utils.collapse_rfc2231_value(part.get_param('DelSp', 'no')).lower()

                if self.STRIP_SIGNATURE:
                    body_text = self.strip_signature(body_text)

                # Get contents charset (iso-8859-15 if not defined in mail headers)
                #
                charset = part.get_content_charset()
                if not charset:
                    charset = 'iso-8859-15'

                try:
                    ubody_text = unicode(body_text, charset)

                except UnicodeError, detail:
                    ubody_text = unicode(body_text, 'iso-8859-15')

                except LookupError, detail:
                    ubody_text = 'ERROR: Could not find charset: %s, please install' %(charset)

                message_parts.append('%s' %ubody_text)
            else:
                if self.DEBUG:
                    print 'TD:               Filename: %s' % part.get_filename()

                message_parts.append((part.get_filename(), part))
        return message_parts

    def unique_attachment_names(self, message_parts):
        renamed_parts = []
        attachment_names = set()
        for part in message_parts:

            # If not an attachment, leave it alone
            if not isinstance(part, tuple):
                renamed_parts.append(part)
                continue

            (filename, part) = part
            # Decode the filename
            if filename:
                filename = self.email_to_unicode(filename)
            # If no name, use a default one
            else:
                filename = 'untitled-part'

                # Guess the extension from the content type, use non strict mode
                # some additional non-standard but commonly used MIME types
                # are also recognized
                #
                ext = mimetypes.guess_extension(part.get_content_type(), False)
                if not ext:
                    ext = '.bin'

                filename = '%s%s' % (filename, ext)

            # Discard relative paths in attachment names
            filename = filename.replace('\\', '/').replace(':', '/')
            filename = os.path.basename(filename)

            # We try to normalize the filename to utf-8 NFC if we can.
            # Files uploaded from OS X might be in NFD.
            # Check python version and then try it
            #
            if sys.version_info[0] > 2 or (sys.version_info[0] == 2 and sys.version_info[1] >= 3):
                try:
                    filename = unicodedata.normalize('NFC', unicode(filename, 'utf-8')).encode('utf-8')
                except TypeError:
                    pass

            # Make the filename unique for this rack
            num = 0
            unique_filename = filename
            filename, ext = os.path.splitext(filename)

            while unique_filename in attachment_names:
                num += 1
                unique_filename = "%s-%s%s" % (filename, num, ext)

            if self.DEBUG:
                print 'TD: Attachment with filename %s will be saved as %s' % (filename, unique_filename)

            attachment_names.add(unique_filename)

            renamed_parts.append((filename, unique_filename, part))

        return renamed_parts

    def inline_part(self, part):
        return part.get_param('inline', None, 'Content-Disposition') == '' or not part.has_key('Content-Disposition')



    def body_text(self, message_parts):
        body_text = []

        for part in message_parts:
            # Plain text part, append it
            if not isinstance(part, tuple):
                body_text.extend(part.strip().splitlines())
                body_text.append("")
                continue

        body_text = '\r\n'.join(body_text)
        self._body_text = body_text
        return body_text


    def get_photos(self, message_parts):
        """save an attachment as a single photo
        """
        # Get Maxium attachment size
        #
        max_size = self.MAX_ATTACHMENT_SIZE
        status   = ''
        results = {}
        
        for part in message_parts:
            # Skip text body parts
            if not isinstance(part, tuple):
                continue

            (original, filename, part) = part
            # Skip html attachments and the like.
            if not part.get_content_type().startswith('image'):
                continue

            text = part.get_payload(decode=1)
            if not text:
                continue
            file_size = len(text)

            # Check if the attachment size is allowed
            #
            if (max_size != -1) and (file_size > max_size):
                status = '%s\nFile %s is larger than allowed attachment size (%d > %d)\n\n' \
                        %(status, original, file_size, max_size)
                continue

            # We use SimpleUploadedFile because it conveniently
            # supports the subset of file-like behavior needed by
            # poster.  Too bad, that's the last reason we really need
            # to import anything from django.
            results[u'photo'] = SimpleUploadedFile.from_dict(
                {'filename': filename, 'content': text,
                 'content-type': part.get_content_type()})
            # XXX what to do if there's more than one attachment?
            # we just ignore 'em.
            break
        return results


    def bounce(self, subject, body, notify_admin='', notify_admin_body=''):
        """Bounce a message to the sender, with additional subject
        and body for explanation.

        If the notify_admin string is non-empty, the site admin will
        be notified, with that string appended to the subject.
        If notify_admin_body is non-empty, it will be added to the body
        sent to the admin.
        """
        if self.DEBUG:
            print "TD: Bouncing message to %s" % self.email_addr
        body += '\n\n------------ original message follows ---------\n\n'
        # TO DO: use attachments rather than inline.
        body += unicode(self.msg.as_string(), errors='ignore')
        if notify_admin:
            admin_subject = 'FixCity handle_mailin bounce! %s' % notify_admin
            admin_body = 'Bouncing to: %s\n' % self.msg['to']
            admin_body += 'Bounce subject: %r\n' % subject
            admin_body += 'Time: %s\n' % datetime.now().isoformat(' ')
            admin_body += 'Not attaching original body, check the log file.\n'
            if notify_admin_body:
                admin_body += 'Additional info:\n'
                admin_body += notify_admin_body
            self.notify_admin(admin_subject, admin_body)
        return self.reply(subject, body)
        
    def reply(self, subject, body):
        send_mail(subject, body, self.msg['to'], [self.email_addr],
                  fail_silently=False)

    def notify_admin(self, subject, body):
        admin_email = settings.SERVICE_FAILURE_EMAIL
        if self.msg and self.msg.get('to'):
            from_addr = self.msg['to']
        else:
            from_addr = 'racks@fixcity.org'
        send_mail(subject, body, from_addr, [admin_email], fail_silently=False)


def _find_in_list(astr, alist):
    alist = alist or []
    for s in alist:
        if s.count(astr):
            return True
    return False

def adapt_errors(errors):
    """Convert the form field names in the errors dict into things
    that are meaningful via the email workflow, and adjust error
    messages appropriately too.
    """
    adapted = {}
    key_mapping = {
        'title': 'subject',
        'address': 'subject',
        'description': 'body',
        }

    val_mapping = {
        ('subject', 'This field is required.'): 
        ("Your subject line should follow this format:\n\n"
         "  Key Foods @224 McGuinness Blvd, Brooklyn NY\n\n"
         "First comes the name of the establishment"
         "(store, park, office etc.) you want a rack near.\n"
         "Then enter @ followed by the address.\n"
         ),

        ("location", "No geometry value provided."):
        ("The address didn't come through properly. Your subject line\n"
         "should follow this format:\n\n"
         "  Key Foods @224 McGuinness Blvd, Brooklyn NY\n\n"
         "Make sure you have the street, city, and state listed after\n"
         "the @ sign in this exact format.\n"),
        }

    for key, vals in errors.items():
        for val in vals:
            key = key_mapping.get(key, key)
            val = val_mapping.get((key, val), val)
            adapted[key] = adapted.get(key, ()) + (val,)
    
    return adapted


class Command(BaseCommand):
    option_list = BaseCommand.option_list + (
        make_option('--url', '-u', help="URL to post racks to", action="store"),
        make_option('--dry-run', action="store_true",
                    help="Don't save any data.", dest="dry_run"),
        make_option('--debug', type="int", default=0,
                    help="Add some verbosity and save any problematic data."),
        make_option('--strip-signature', action="store_true", default=True,
                    help="Remove signatures from incoming mail"),
        make_option('--max-attachment-size', type="int",
                    help="Max size of uploaded files."),
    )

    def handle(self, *args, **options):
        assert options['url'] is not None
        parser = EmailParser(options)
        did_stdin = False
        for filename in args:
            now = datetime.now().isoformat(' ')
            print "------------- %s ------------" % now
            if filename == '-':
                if did_stdin:
                    continue
                thisfile = sys.stdin
                did_stdin = True
            else:
                thisfile = open(filename)
            try:
                raw_msg = thisfile.read()
                parser.parse(raw_msg)
            except:
                tb_msg = "Exception at %s follows:\n------------\n" % now
                tb_msg += traceback.format_exc()
                tb_msg += "\n -----Original message follows ----------\n\n"
                tb_msg += raw_msg
                if parser.msg:
                    parser.save_email_for_debug(parser.msg)
                parser.notify_admin('Unexpected traceback in handle_mailin',
                                    tb_msg)
                raise
