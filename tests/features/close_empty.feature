Feature: Close empty terminals safely
  The close-empty command should find prompt-only scratch terminals
  while leaving active or multi-session terminals alone.

  Scenario: Wayland fallback keeps active terminals and closes empty scratch windows
    Given the live Wayland fallback fixture
    When I select close-empty candidates from that fixture
    Then the close candidates should equal "qmlkonsole:944645,yakuake:955961"
    And the protected terminals should equal "konsole:2073,qterminal:348869,xfce4-terminal:1067483"
