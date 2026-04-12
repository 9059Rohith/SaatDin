import 'package:flutter_test/flutter_test.dart';

import 'package:saatdin/main.dart';

void main() {
  testWidgets('SaatDin app renders auth entry flow', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(const SaatDinApp());
    await tester.pump(const Duration(milliseconds: 400));
    await tester.pump(const Duration(milliseconds: 400));

    final isBootstrapVisible = find
        .text('Restoring your coverage session...')
        .evaluate()
        .isNotEmpty;
    final isOnboardingVisible =
        find.text('Next').evaluate().isNotEmpty ||
        find.text('Get Started').evaluate().isNotEmpty;
    final isWelcomeVisible = find.text('Continue').evaluate().isNotEmpty;

    expect(
      isBootstrapVisible || isOnboardingVisible || isWelcomeVisible,
      isTrue,
    );
  });
}
