class MetaDataContainer:
    event = None


def pre_save(instance, user):
    # ruleid: state-on-meta
    instance._meta.changed_by = user
    # ruleid: state-on-meta
    setattr(instance._meta, "reason", "import")


def audit_pre_save(instance, event):
    if not hasattr(instance._meta, "dal"):
        # ruleid: state-on-meta
        instance._meta.dal = MetaDataContainer()
    # ruleid: state-on-meta
    instance._meta.dal.event = event
    # ruleid: state-on-meta
    instance._meta.extra["event"] = event


def fine(instance, user):
    # ok: state-on-meta
    instance._changed_by = user
    # ok: state-on-meta
    return instance._meta.label
