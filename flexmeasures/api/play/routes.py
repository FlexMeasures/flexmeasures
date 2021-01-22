from flask_security import auth_token_required, roles_required

from flexmeasures.api.play import (
    flexmeasures_api as flexmeasures_api_play,
    implementations as play_implementations,
)


@flexmeasures_api_play.route("/restoreData", methods=["PUT"])
@auth_token_required
@roles_required("admin")
def restore_data():
    """API endpoint to restore the database to one of the saved backups.

    .. :quickref: Admin; Restore the database to a known backup

    **Example request**

    This message restores the database to a backup named demo_v0.

    .. code-block:: json

        {
            "backup": "demo_v0"
        }

    **Example response**

    This message indicates that the backup has been restored without any error.

    .. sourcecode:: json

        {
            "message": "Request has been processed. Database restored to demo_v0.",
            "status": "PROCESSED"
        }

    :reqheader Authorization: The authentication token
    :reqheader Content-Type: application/json
    :resheader Content-Type: application/json
    :status 200: PROCESSED
    :status 400: NO_BACKUP, UNRECOGNIZED_BACKUP
    :status 401: UNAUTHORIZED
    :status 405: INVALID_METHOD
    """
    return play_implementations.restore_data_response()
