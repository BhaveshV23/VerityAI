type DocumentViewerProps = {
  text: string;
};

export default function DocumentViewer({ text }: DocumentViewerProps) {
  return (
    <section className="document-panel panel" aria-labelledby="document-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Submitted source</p>
          <h2 id="document-heading">Original text</h2>
        </div>
        <span className="version-chip">Immutable version</span>
      </div>
      <article className="document-copy">{text || 'The submitted text is not available in this browser session.'}</article>
    </section>
  );
}
