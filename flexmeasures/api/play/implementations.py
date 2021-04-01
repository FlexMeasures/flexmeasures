from pathlib import Path

from flask import request, current_app as app
from flask_json import as_json

from flexmeasures.api.common.responses import (
    no_backup,
    request_processed,
    unrecognized_backup,
)
from flexmeasures.data.config import db
from flexmeasures.data.scripts.data_gen import (
    depopulate_measurements,
    depopulate_prognoses,
    depopulate_structure,
    get_affected_classes,
    load_tables,
)


@as_json
def restore_data_response():

    delete_structure = True
    delete_data = True
    restore_structure = True
    restore_data = True

    try:
        backup_name = request.args.get("backup", request.json["backup"])
    except KeyError:
        return no_backup()

    # Make sure backup folder and files exist before restoring
    backup_path = app.config.get("FLEXMEASURES_DB_BACKUP_PATH")
    if (
        not Path("%s/%s" % (backup_path, backup_name)).exists()
        or not Path("%s/%s" % (backup_path, backup_name)).is_dir()
    ):
        return unrecognized_backup()
    affected_classes = get_affected_classes(
        structure=restore_structure, data=restore_data
    )
    for c in affected_classes:
        file_path = "%s/%s/%s.obj" % (backup_path, backup_name, c.__tablename__)
        if not Path(file_path).exists():
            return unrecognized_backup(
                "Can't load table, because filename %s does not exist."
                % c.__tablename__
            )

    # Reset in play mode only (this endpoint should not have been registered otherwise)
    assert app.config.get("FLEXMEASURES_MODE", "") == "play"
    if delete_data:
        depopulate_prognoses(db)
        depopulate_measurements(db)
    if delete_structure:
        depopulate_structure(db)

    # Load backup
    load_tables(
        db,
        backup_name,
        structure=restore_structure,
        data=restore_data,
        backup_path=backup_path,
    )

    return request_processed("Database restored to %s." % backup_name)
