export default function Terms() {
  return (
    <div className="terms-page">
      <h2>◈ TERMS OF SERVICE</h2>
      <p><em>Last updated: June 2026</em></p>

      <h3>1. Acceptance of Terms</h3>
      <p>By accessing or using Klyra, you acknowledge that you have read, understood, and agree to be bound by these terms. If you do not agree, do not use the service. This platform is provided for authorized security testing and educational purposes only.</p>

      <h3>2. Service Description</h3>
      <p>Klyra provides a self-hosted AI-assisted security lab. Operators can create isolated workspaces, run authorized assessments, capture evidence, and draft remediation notes.</p>

      <h3>3. User Responsibilities</h3>
      <p>You represent and warrant that: (a) you have the legal authority to test any target systems; (b) you will comply with all applicable local, state, national, and international laws; (c) you will not use the service for any unlawful purpose; (d) you are at least 18 years of age.</p>

      <h3>4. Prohibited Uses</h3>
      <p>You may not use Klyra to: (a) attack systems you do not own or have explicit permission to test; (b) disrupt critical infrastructure; (c) steal or exfiltrate data without authorization; (d) distribute malware; (e) engage in any activity that violates applicable law.</p>

      <h3>5. Data Storage</h3>
      <p>Klyra stores operational metadata on your self-hosted instance. Instance owners are responsible for configuring retention, backups, access control, and disclosure requirements.</p>

      <h3>6. Access</h3>
      <p>Access is managed by the owner or administrator of each self-hosted instance. The open-source project does not sell hosted access from this repository.</p>

      <h3>7. Limitation of Liability</h3>
      <p>Klyra is provided "as is" without warranty of any kind. In no event shall the operators be liable for any damages arising from the use or inability to use the service, including but not limited to unauthorized access to your systems or data breaches resulting from your use of the platform.</p>

      <h3>8. Changes to Terms</h3>
      <p>We reserve the right to modify these terms at any time. Continued use of the service after changes constitutes acceptance of the new terms.</p>

      <h3>9. Governing Law</h3>
      <p>These terms shall be governed by the laws of a jurisdiction to be determined at the sole discretion of the operators, with no regard to conflict of law principles. Any disputes shall be resolved through binding arbitration.</p>

      <div style={{ marginTop: '40px', padding: '16px', border: '1px solid var(--border)', textAlign: 'center' }}>
        <p style={{ fontFamily: "'Press Start 2P', monospace", fontSize: '0.45rem', color: '#555577' }}>
          BY USING THIS SERVICE, YOU ACKNOWLEDGE THAT YOU ARE SOLELY RESPONSIBLE FOR YOUR ACTIONS.
        </p>
      </div>
    </div>
  )
}
