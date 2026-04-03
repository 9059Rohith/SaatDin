import 'package:flutter/material.dart';
import '../screens/onboarding/onboarding_screen.dart';
import '../screens/auth/auth_bootstrap_screen.dart';
import '../screens/auth/check_worker_status_screen.dart';
import '../screens/welcome_screen.dart';
import '../screens/otp_verification_screen.dart';
import '../screens/onboarding/name_input_screen.dart';
import '../screens/onboarding/platform_selection_screen.dart';
import '../screens/onboarding/zone_selection_screen.dart';
import '../screens/onboarding/plan_selection_screen.dart';
import '../screens/main_shell.dart';

class AppRoutes {
  AppRoutes._();

  static const String onboarding = '/onboarding';
  static const String bootstrap = '/bootstrap';
  static const String welcome = '/welcome';
  static const String otpVerify = '/otp-verify';
  static const String checkWorkerStatus = '/check-worker-status';
  static const String nameInput = '/name-input';
  static const String platformSelect = '/platform-select';
  static const String zoneSelect = '/zone-select';
  static const String planSelect = '/plan-select';
  static const String home = '/home';

  static Map<String, WidgetBuilder> get routes {
    return {
      onboarding: (context) => const OnboardingScreen(),
      bootstrap: (context) => const AuthBootstrapScreen(),
      welcome: (context) => const WelcomeScreen(),
      otpVerify: (context) => const OtpVerificationScreen(),
      checkWorkerStatus: (context) => const CheckWorkerStatusScreen(),
      nameInput: (context) => const NameInputScreen(),
      platformSelect: (context) => const PlatformSelectionScreen(),
      zoneSelect: (context) => const ZoneSelectionScreen(),
      planSelect: (context) => const PlanSelectionScreen(),
      home: (context) => const MainShell(),
    };
  }
}
