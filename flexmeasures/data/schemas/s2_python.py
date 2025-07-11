from marshmallow import Schema, fields
from marshmallow.validate import OneOf
from enum import Enum


# Enums for the protocol and other fields
class EncryptionAlgorithm(str, Enum):
    RSA_OAEP_256 = "RSA-OAEP-256"


class S2Role(str, Enum):
    CEM = "CEM"
    RM = "RM"


class Deployment(str, Enum):
    WAN = "WAN"
    LAN = "LAN"


class Protocols(str, Enum):
    WebSocketSecure = "WebSocketSecure"


# Marshmallow schemas for validation
class S2NodeDescriptionSchema(Schema):
    brand = fields.Str(required=True)
    logoUri = fields.Str(required=True)
    type = fields.Str(required=True)
    modelName = fields.Str(required=True)
    userDefinedName = fields.Str(required=True)
    role = fields.Str(required=True, validate=OneOf([e.value for e in S2Role]))
    deployment = fields.Str(
        required=True, validate=OneOf([e.value for e in Deployment])
    )


class PairingRequestSchema(Schema):
    token = fields.Str(required=True)
    publicKey = fields.Str(required=True)
    encryptionAlgorithm = fields.Str(
        required=True, validate=OneOf([e.value for e in EncryptionAlgorithm])
    )
    s2ClientNodeId = fields.Str(required=True)
    s2ClientNodeDescription = fields.Nested(S2NodeDescriptionSchema, required=True)
    supportedProtocols = fields.List(
        fields.Str(validate=OneOf([e.value for e in Protocols])), required=True
    )


class PairingResponseSchema(Schema):
    s2ServerNodeId = fields.Str(required=True)
    serverNodeDescription = fields.Nested(S2NodeDescriptionSchema, required=True)
    requestConnectionUri = fields.Str(required=True)


class ConnectionRequestSchema(Schema):
    s2ClientNodeId = fields.Str(required=True)
    supportedProtocols = fields.List(
        fields.Str(validate=OneOf([e.value for e in Protocols])), required=True
    )
