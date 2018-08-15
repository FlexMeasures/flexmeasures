from pathlib import Path

from flask import request, current_app as app
from flask_json import as_json

from bvp.api.common.responses import no_backup, request_processed, unrecognized_backup
from bvp.data.config import db
from bvp.data.static_content import (
    depopulate_data,
    depopulate_forecasts,
    depopulate_structure,
    get_affected_classes,
    load_tables,
)


@as_json
def restore_data_response():

    structure = True
    data = False

    try:
        backup_name = request.args.get("backup", request.json["backup"])
    except KeyError:
        return no_backup()

    # Make sure backup folder and files exist before restoring
    backup_path = app.config.get("BVP_DB_BACKUP_PATH")
    if (
        not Path("%s/%s" % (backup_path, backup_name)).exists()
        or not Path("%s/%s" % (backup_path, backup_name)).is_dir()
    ):
        return unrecognized_backup()
    affected_classes = get_affected_classes(structure=structure, data=data)
    for c in affected_classes:
        file_path = "%s/%s/%s.obj" % (backup_path, backup_name, c.__tablename__)
        if not Path(file_path).exists():
            return unrecognized_backup(
                "Can't load table, because filename %s does not exist."
                % c.__tablename__
            )

    # Reset in play mode only (this endpoint should not have been registered otherwise)
    assert app.config.get("BVP_MODE", "") == "play"
    if data:
        depopulate_forecasts(db)
        depopulate_data(db)
    if structure:
        depopulate_structure(db)

    # Load backup
    load_tables(
        db, backup_name, structure=structure, data=data, backup_path=backup_path
    )

    return request_processed("Database restored to %s." % backup_name)
