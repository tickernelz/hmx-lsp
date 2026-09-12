{
    "name": "demo",
    "version": "1.0",
    "depends": ["base"],
    "data": [
        "security/ir.model.access.csv",
        "views/order.xml",
    ],
    "assets": {
        "webx.assets_backend": [
            "static/js/widget.js",
            "static/css/*.css",
            "static/js/missing/*.js",
        ],
    },
}
