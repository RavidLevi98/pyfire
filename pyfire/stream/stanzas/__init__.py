# -*- coding: utf-8 -*-
"""
    pyfire.stream.stanzas
    ~~~~~~~~~~~~~~~~~~~~~~

    Process stream events and redirect to tag handlers

    :copyright: 2011 by the pyfire Team, see AUTHORS for more details.
    :license: BSD, see LICENSE for more details.
"""

import uuid
from thread import allocate_lock
import xml.etree.ElementTree as ET

import zmq
from zmq.eventloop.zmqstream import ZMQStream

from pyfire.auth.sasl import SASLAuthHandler, MalformedRequestError
import pyfire.configuration as config
from pyfire.jid import JID
from pyfire.logger import Logger
from pyfire.singletons import get_publisher, get_known_jids
from pyfire.stream.errors import *

log = Logger(__name__)

BIND_NS="urn:ietf:params:xml:ns:xmpp-bind"
SESSION_NS="urn:ietf:params:xml:ns:xmpp-session"


class TagHandler(object):

    def __init__(self, connection):
        super(TagHandler, self).__init__()
        self.connection = connection
        self.send_element = connection.send_element
        self.send_string = connection.send_string

        self.jid = None
        self.hostname = None

        self.authenticated = False
        self.session_active = False
        self.publisher = get_publisher()

    def contenthandler(self, tree):
        """Handles an incomming content tree"""

        # set/replace the from attribute in stanzas as required
        # by RFC 6120 Section 8.1.2.1
        if self.authenticated:
            tree.set("from", str(self.jid))

        try:
            if tree.tag == "auth":
                if self.authenticated:
                    raise NotAllowedError
                self.authenticate(tree)

            elif tree.tag == "iq":
                if not self.authenticated:
                    raise NotAuthorizedError
                if self.jid.resource is None:
                    self.set_resource(tree)
                else:
                    if not self.session_active:
                        first_element = tree[0]
                        if first_element.tag == "session" and \
                                first_element.get("xmlns") == SESSION_NS:
                            response_element = ET.Element("iq")
                            response_element.set("type", "result")
                            response_element.set("id", tree.get("id"))
                            session_element = ET.SubElement(response_element, "session")
                            session_element.set("xmlns", SESSION_NS)
                            self.send_element(response_element)
                            log.debug("Sent empty session element")
                            self.processed_stream.stop_on_recv()
                            self.processed_stream.on_recv(self.send_string)
                        else:
                            self.publish_stanza(tree)
                    else:
                        self.publish_stanza(tree)

            elif tree.tag in ["message", "presence"]:
                if not self.authenticated:
                    raise NotAuthorizedError
                self.publish_stanza(tree)

        except StreamError, e:
            self.send_string(unicode(e))
            self.connection.stop_connection()

    def publish_stanza(self, tree):
        stanza = ET.tostring(tree)
        log.debug("Publishing Stanza for topic %s: %s" % (tree.get("from"),stanza))
        self.publisher.send(tree.get("from"), stanza)

    def masked_send_string(self, msg):
        """Unmark waiting for a session element if we received another stanza response"""

        self.session_active = True
        self.processed_stream.stop_on_recv()
        self.processed_stream.on_recv(self.send_string)
        self.send_string(msg)

    def set_resource(self, tree):
        """Set a resource on our JID"""

        bind_element = tree[0]
        if tree.get("type") != "set" or \
                bind_element.tag != 'bind' or\
                bind_element.get("xmlns") != BIND_NS:
            raise NotAuthorizedError

        resource_element = bind_element.find("resource")
        if resource_element is None:
            # No prefered resource was set, generate one
            self.jid.resource = uuid.uuid4().hex
        else:
            self.jid.resource = resource_element.text
        if not self.jid.validate():
            raise BadRequestError

        # Check if given resource is already in use
        known_jids = get_known_jids()
        try:
            known_jids.append(self.jid)
        except ValueError:
            raise ConflictError
        log.info("Bound connection as %s" % str(self.jid))

        # Send registered resource back to client
        response_element = ET.Element("iq")
        response_element.set("type", "result")
        response_element.set("id", tree.get("id"))
        bind_element = ET.SubElement(response_element, "bind")
        bind_element.set("xmlns", BIND_NS)
        jid_element = ET.SubElement(bind_element, "jid")
        jid_element.text = str(self.jid)
        self.send_element(response_element)

    def authenticate(self, tree):
        """Authenticates user for session"""

        # Currently RFC specifies only SASL as supported way of auth'ing
        handler = SASLAuthHandler()
        if tree.get('xmlns') != handler.namespace:
            raise MalformedRequestError
        handler.process(tree)
        self.connection.parser.reset()
        self.jid = JID("@".join([handler.authenticated_user,
                                 self.hostname]))
        self.authenticated = True
        response_element = ET.Element("success")
        response_element.set("xmlns", handler.namespace)
        self.send_element(response_element)

        # Subscribe to stanza responses
        processed_stanzas_socket = zmq.Context().socket(zmq.SUB)
        processed_stanzas_socket.connect(self.publisher.sub_url)
        processed_stanzas_socket.setsockopt(zmq.SUBSCRIBE, str(self.jid))

        self.processed_stream = ZMQStream(processed_stanzas_socket,
                                          self.connection.stream.io_loop)
        self.processed_stream.on_recv(self.masked_send_string)

    def add_auth_options(self, feature_element):
        """Add supported auth mechanisms to feature element"""

        handler = SASLAuthHandler()
        mechtype_element = ET.SubElement(feature_element, "mechanisms")
        mechtype_element.set("xmlns", handler.namespace)
        for mech in handler.supported_mechs:
            mech_element = ET.SubElement(mechtype_element, 'mechanism')
            mech_element.text = mech

    def add_server_features(self, feature_element):
        bind = ET.SubElement(feature_element, "bind")
        bind.set("xmlns", "urn:ietf:params:xml:ns:xmpp-bind")

        # Session establishment is deprecated in RFC6121 but Appendix E
        # suggests to still advertise it as feature for compatibility.
        session = ET.SubElement(feature_element, "session")
        session.set("xmlns", "urn:ietf:params:xml:ns:xmpp-session")

    def streamhandler(self, attrs):
        """Handles a stream start"""

        if attrs == {}:
            # </stream:stream> received
            self.connection.stop_connection()
        else:
            # check if we are responsible for this stream
            self.hostname = attrs.getValue("to")
            if self.hostname not in config.getlist("listeners", "domains"):
                raise HostUnknownError

            # Stream restart
            stream = ET.Element("stream:stream")
            stream.set("xmlns", attrs.getValue("xmlns"))
            stream.set("from", self.hostname)
            stream.set("id", uuid.uuid4().hex)
            stream.set("xml:lang", "en")
            stream.set("xmlns:stream", "http://etherx.jabber.org/streams")

            # only include version in response if client sent its max supported
            # version (RFC6120 Section 4.7.5)
            try:
                if attrs.getValue("version") != "1.0":
                    raise UnsupportedVersionError
                stream.set("version", "1.0")
            except KeyError:
                pass

            try:
                from_jid = JID(attrs.getValue("from"))
                stream.set("to", unicode(from_jid))
            except ValueError:
                raise InvalidFromError
            except KeyError:
                pass

            start_stream = """<?xml version="1.0"?>""" + ET.tostring(stream)
            # Element has subitems but are added later to the stream,
            # so don't mark it a single element
            self.send_string(start_stream.replace("/>", ">"))

            # Make a list of supported features
            features = ET.Element("stream:features")
            if not self.authenticated:
                self.add_auth_options(features)
            else:
                self.add_server_features(features)

            self.send_element(features)
