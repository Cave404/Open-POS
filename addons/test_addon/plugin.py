from flask import Blueprint, jsonify

blueprint = Blueprint('test_addon', __name__)

@blueprint.route('/status', methods=['GET'])
def addon_status():
    return jsonify({
        "status": "ok",
        "addon": "test_addon",
        "message": "Test Addon operational"
    })

def on_sale_complete(data=None):
    return {"status": "ok", "hook": "on_sale_complete"}

hooks = {
    "on_sale_complete": on_sale_complete
}
