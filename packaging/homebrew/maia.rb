class Maia < Formula
  include Language::Python::Virtualenv

  desc "Private one-tenant corporate AI assistant with gateway, governance, and automation controls"
  homepage "https://ampliia.com/en/maia/docs/"
  url "https://github.com/and270/maia/releases/download/v2026.5.7/maia-0.13.0.tar.gz"
  sha256 "<replace-with-release-asset-sha256>"
  license "Internal proprietary distribution; includes MIT-licensed upstream Hermes Agent components"

  depends_on "certifi" => :no_linkage
  depends_on "cryptography" => :no_linkage
  depends_on "libyaml"
  depends_on "python@3.14"

  pypi_packages ignore_packages: %w[certifi cryptography pydantic]

  # Refresh resource stanzas after bumping the source url/version:
  #   brew update-python-resources --print-only maia

  def install
    venv = virtualenv_create(libexec, "python3.14")
    venv.pip_install resources
    venv.pip_install buildpath

    pkgshare.install "skills", "optional-skills"

    %w[maia maia-agent maia-acp].each do |exe|
      next unless (libexec/"bin"/exe).exist?

      (bin/exe).write_env_script(
        libexec/"bin"/exe,
        MAIA_BUNDLED_SKILLS: pkgshare/"skills",
        MAIA_OPTIONAL_SKILLS: pkgshare/"optional-skills",
        MAIA_MANAGED: "homebrew"
      )
    end
  end

  test do
    assert_match "Maia v#{version}", shell_output("#{bin}/maia version")

    managed = shell_output("#{bin}/maia update 2>&1")
    assert_match "managed by Homebrew", managed
    assert_match "brew upgrade maia", managed
  end
end
