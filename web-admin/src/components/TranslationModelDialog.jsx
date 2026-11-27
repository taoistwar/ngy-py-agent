import Modal from "./admin/Modal"

/**
 * Shown when the log's translate action is used while no translation model is set.
 *
 * The fix is a setting, so the dialog offers the page that owns it rather than an
 * error the reader has to interpret ("400: no translation model").
 */
export default function TranslationModelDialog({ translate, onConfigure, onClose }) {
  return (
    <Modal
      title={translate("translationNoModelTitle")}
      hint={translate("translationNoModelHint")}
      closeLabel={translate("translationNoModelCancel")}
      onClose={onClose}
    >
      <div className="permission-prompt">
        <p className="hint">{translate("translationNoModelBody")}</p>
        <div className="permission-actions">
          <button type="button" className="btn btn-primary" onClick={onConfigure}>
            {translate("translationNoModelConfigure")}
          </button>
          <button type="button" className="btn" onClick={onClose}>
            {translate("translationNoModelCancel")}
          </button>
        </div>
      </div>
    </Modal>
  )
}
