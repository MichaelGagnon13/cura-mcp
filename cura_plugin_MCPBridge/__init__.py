from . import MCPBridge

def getMetaData():
    return {}

def register(app):
    return {"extension": MCPBridge.MCPBridge()}
