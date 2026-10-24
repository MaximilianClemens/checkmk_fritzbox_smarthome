from cmk.rulesets.v1.form_specs import (
    Dictionary,
    DictElement,
    String,
    Password,
    Integer,
    SingleChoice,
    SingleChoiceElement,
    BooleanChoice,
    DefaultValue,
    migrate_to_password
)
from cmk.rulesets.v1.rule_specs import SpecialAgent, Topic, Help, Title


def _formspec():
    return Dictionary(
        title=Title("Fritz!Box Smarthome Devices"),
        help_text=Help("Configure access to the Fritz!Box smarthome data."),
        elements={
            "username": DictElement(
                required=True,
                parameter_form=String(
                    title=Title("Username"),
                    help_text=Help("Username for login."),
                    prefill=DefaultValue("smarthome"),
                ),
            ),
            "password": DictElement(
                required=True,
                parameter_form=Password(
                    title=Title("Password"),
                    help_text=Help("Password for the user."),
                    migrate=migrate_to_password,
                ),
            ),
            "port": DictElement(
                required=True,
                parameter_form=Integer(
                    title=Title("Port"),
                    help_text=Help("Port number of the Fritz!Box."),
                    prefill=80,
                ),
            ),
            "protocol": DictElement(
                required=True,
                parameter_form=SingleChoice(
                    title=Title("Protocol"),
                    help_text=Help("Select whether to use HTTP or HTTPS."),
                    elements=[
                        SingleChoiceElement("http", Title("HTTP")),
                        SingleChoiceElement("https", Title("HTTPS")),
                    ],
                    prefill=DefaultValue("http"),
                ),
            ),
            "ignore_ssl": DictElement(
                required=True,
                parameter_form=BooleanChoice(
                    title=Title("Ignore SSL certificate"),
                    help_text=Help("Disable SSL certificate verification."),
                    prefill=DefaultValue(False),
                ),
            ),
            # optional: rules created with older versions do not have this key
            # and behave like "auto"
            "login_method": DictElement(
                required=False,
                parameter_form=SingleChoice(
                    title=Title("Login method"),
                    help_text=Help(
                        "How to answer the login challenge of the Fritz!Box. "
                        "Automatic uses PBKDF2 when the box offers it (Fritz!OS 7.24 and newer) "
                        "and falls back to MD5 otherwise. Choose a fixed method only if the "
                        "automatic detection does not work for your box."
                    ),
                    elements=[
                        SingleChoiceElement("auto", Title("Automatic (PBKDF2 if available, otherwise MD5)")),
                        SingleChoiceElement("pbkdf2", Title("PBKDF2 (Fritz!OS 7.24 and newer)")),
                        SingleChoiceElement("md5", Title("MD5 (legacy, Fritz!OS before 7.24)")),
                    ],
                    prefill=DefaultValue("auto"),
                ),
            ),
        },
    )

rule_spec_fritzbox_smarthome = SpecialAgent(
    topic=Topic.NETWORKING,
    name="fritzbox_smarthome",
    title=Title("Fritz!Box Smarthome Devices"),
    parameter_form=_formspec,
)
