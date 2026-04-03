import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:google_fonts/google_fonts.dart';
import '../../theme/app_colors.dart';
import '../../routes/app_routes.dart';

// ─────────────────────────────────────────────────────────────────────────────
// Slide data model
// ─────────────────────────────────────────────────────────────────────────────

class _OnboardingSlide {
  final IconData icon;
  final Color iconColor;
  final Color iconBg;
  final String headline;
  final String subheadline;
  final String body;

  const _OnboardingSlide({
    required this.icon,
    required this.iconColor,
    required this.iconBg,
    required this.headline,
    required this.subheadline,
    required this.body,
  });
}

const List<_OnboardingSlide> _slides = [
  _OnboardingSlide(
    icon: Icons.electric_bolt_rounded,
    iconColor: Color(0xFF13B8AA),
    iconBg: Color(0xFFE6F8F6),
    headline: 'Zero-Touch Payouts',
    subheadline: 'No forms. No calls. No waiting.',
    body:
        'When heavy rain, floods, or severe traffic shut down your delivery zone, '
        'SaatDin detects it automatically and sends money straight to your UPI — '
        'usually before you even reach home.',
  ),
  _OnboardingSlide(
    icon: Icons.my_location_rounded,
    iconColor: Color(0xFF0E8D83),
    iconBg: Color(0xFFD1FAE5),
    headline: 'Pincode-Precise Coverage',
    subheadline: 'Your zone. Your payout.',
    body:
        'Disruptions are tracked at the pincode level. A flood in Bellandur '
        "doesn't trigger a payout for a rider in Whitefield. "
        'Coverage is always relevant to exactly where you work.',
  ),
  _OnboardingSlide(
    icon: Icons.currency_rupee_rounded,
    iconColor: Color(0xFFF59E0B),
    iconBg: Color(0xFFFEF3C7),
    headline: 'Weekly Premium, Big Safety Net',
    subheadline: 'From ₹29 / week.',
    body:
        'Pay a small weekly premium — auto-debited every Monday via UPI. '
        'Get up to ₹500 back for every qualifying disruption day. '
        'Cancel anytime, no lock-in.',
  ),
];

// ─────────────────────────────────────────────────────────────────────────────
// Main widget
// ─────────────────────────────────────────────────────────────────────────────

class OnboardingScreen extends StatefulWidget {
  const OnboardingScreen({super.key});

  @override
  State<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends State<OnboardingScreen>
    with TickerProviderStateMixin {
  final PageController _pageController = PageController();
  int _currentPage = 0;

  // Per-page animation controllers
  late final List<AnimationController> _slideControllers;
  late final List<Animation<double>> _fadeAnims;
  late final List<Animation<Offset>> _slideAnims;

  @override
  void initState() {
    super.initState();
    SystemChrome.setSystemUIOverlayStyle(SystemUiOverlayStyle.dark);

    _slideControllers = List.generate(
      _slides.length,
      (_) => AnimationController(
        vsync: this,
        duration: const Duration(milliseconds: 500),
      ),
    );

    _fadeAnims = _slideControllers
        .map((c) => CurvedAnimation(parent: c, curve: Curves.easeOut))
        .toList();

    _slideAnims = _slideControllers
        .map(
          (c) => Tween<Offset>(
            begin: const Offset(0, 0.12),
            end: Offset.zero,
          ).animate(CurvedAnimation(parent: c, curve: Curves.easeOut)),
        )
        .toList();

    // Animate first slide in immediately
    _slideControllers[0].forward();
  }

  @override
  void dispose() {
    for (final c in _slideControllers) {
      c.dispose();
    }
    _pageController.dispose();
    super.dispose();
  }

  void _onPageChanged(int page) {
    setState(() => _currentPage = page);
    _slideControllers[page].forward(from: 0);
  }

  void _goToPrev() {
    if (_currentPage > 0) {
      _pageController.previousPage(
        duration: const Duration(milliseconds: 420),
        curve: Curves.easeInOut,
      );
    }
  }

  void _goToNext() {
    if (_currentPage < _slides.length - 1) {
      _pageController.nextPage(
        duration: const Duration(milliseconds: 420),
        curve: Curves.easeInOut,
      );
    } else {
      _finishOnboarding();
    }
  }

  void _finishOnboarding() {
    Navigator.pushReplacementNamed(context, AppRoutes.bootstrap);
  }

  // ─── Build ──────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.of(context).size;

    return Scaffold(
      backgroundColor: AppColors.background,
      body: SafeArea(
        child: Column(
          children: [
            // ── Top navigation row: Back (left) + Skip (right) ──────────
            Padding(
              padding: const EdgeInsets.only(top: 12, left: 20, right: 20),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  // Back button – hidden on first slide
                  AnimatedOpacity(
                    opacity: _currentPage > 0 ? 1.0 : 0.0,
                    duration: const Duration(milliseconds: 250),
                    child: GestureDetector(
                      onTap: _currentPage > 0 ? _goToPrev : null,
                      child: Container(
                        width: 40,
                        height: 40,
                        decoration: const BoxDecoration(
                          color: AppColors.surfaceLight,
                          shape: BoxShape.circle,
                        ),
                        child: const Icon(
                          Icons.chevron_left_rounded,
                          color: AppColors.textSecondary,
                          size: 24,
                        ),
                      ),
                    ),
                  ),

                  // Skip button – hidden on last slide
                  AnimatedOpacity(
                    opacity: _currentPage < _slides.length - 1 ? 1.0 : 0.0,
                    duration: const Duration(milliseconds: 250),
                    child: GestureDetector(
                      onTap: _finishOnboarding,
                      child: Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 14,
                          vertical: 6,
                        ),
                        decoration: BoxDecoration(
                          color: AppColors.surfaceLight,
                          borderRadius: BorderRadius.circular(20),
                        ),
                        child: Text(
                          'Skip',
                          style: GoogleFonts.inter(
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                            color: AppColors.textSecondary,
                          ),
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),

            // ── Slide pages ─────────────────────────────────────────────
            Expanded(
              child: PageView.builder(
                controller: _pageController,
                itemCount: _slides.length,
                onPageChanged: _onPageChanged,
                itemBuilder: (context, index) {
                  final slide = _slides[index];
                  return FadeTransition(
                    opacity: _fadeAnims[index],
                    child: SlideTransition(
                      position: _slideAnims[index],
                      child: _SlideContent(
                        slide: slide,
                        screenHeight: size.height,
                      ),
                    ),
                  );
                },
              ),
            ),

            // ── Bottom area: dots + CTA button ──────────────────────────
            Padding(
              padding: const EdgeInsets.fromLTRB(28, 0, 28, 32),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  // Progress dots
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: List.generate(_slides.length, (i) {
                      final isActive = i == _currentPage;
                      return AnimatedContainer(
                        duration: const Duration(milliseconds: 300),
                        curve: Curves.easeOut,
                        margin: const EdgeInsets.symmetric(horizontal: 4),
                        width: isActive ? 28 : 8,
                        height: 8,
                        decoration: BoxDecoration(
                          color: isActive
                              ? AppColors.primary
                              : AppColors.border,
                          borderRadius: BorderRadius.circular(4),
                        ),
                      );
                    }),
                  ),

                  const SizedBox(height: 28),

                  // Next / Get Started button
                  SizedBox(
                    width: double.infinity,
                    child: AnimatedContainer(
                      duration: const Duration(milliseconds: 300),
                      decoration: BoxDecoration(
                        borderRadius: BorderRadius.circular(14),
                        color: AppColors.primary,
                        boxShadow: [
                          BoxShadow(
                            color: AppColors.primary.withValues(alpha: 0.35),
                            blurRadius: 16,
                            offset: const Offset(0, 6),
                          ),
                        ],
                      ),
                      child: Material(
                        color: Colors.transparent,
                        borderRadius: BorderRadius.circular(14),
                        child: InkWell(
                          onTap: _goToNext,
                          borderRadius: BorderRadius.circular(14),
                          child: Padding(
                            padding: const EdgeInsets.symmetric(vertical: 18),
                            child: Center(
                              child: Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  Text(
                                    _currentPage == _slides.length - 1
                                        ? 'Get Started'
                                        : 'Next',
                                    style: GoogleFonts.inter(
                                      fontSize: 16,
                                      fontWeight: FontWeight.w700,
                                      color: Colors.white,
                                      letterSpacing: 0.2,
                                    ),
                                  ),
                                  const SizedBox(width: 8),
                                  const Icon(
                                    Icons.arrow_forward_rounded,
                                    color: Colors.white,
                                    size: 18,
                                  ),
                                ],
                              ),
                            ),
                          ),
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Slide content widget
// ─────────────────────────────────────────────────────────────────────────────

class _SlideContent extends StatelessWidget {
  final _OnboardingSlide slide;
  final double screenHeight;

  const _SlideContent({
    required this.slide,
    required this.screenHeight,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 28),
      child: Column(
        children: [
          SizedBox(height: screenHeight * 0.05),

          // ── Illustration card ──────────────────────────────────────
          Container(
            width: double.infinity,
            height: screenHeight * 0.34,
            decoration: BoxDecoration(
              color: slide.iconBg,
              borderRadius: BorderRadius.circular(28),
            ),
            child: Stack(
              alignment: Alignment.center,
              children: [
                // Halo circle behind icon
                Container(
                  width: 130,
                  height: 130,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: slide.iconColor.withValues(alpha: 0.12),
                  ),
                ),
                Icon(
                  slide.icon,
                  size: 80,
                  color: slide.iconColor,
                ),
              ],
            ),
          ),

          SizedBox(height: screenHeight * 0.045),

          // ── Headline ───────────────────────────────────────────────
          Text(
            slide.headline,
            textAlign: TextAlign.center,
            style: GoogleFonts.montserrat(
              fontSize: 26,
              fontWeight: FontWeight.w800,
              color: AppColors.textPrimary,
              letterSpacing: -0.5,
              height: 1.2,
            ),
          ),

          const SizedBox(height: 8),

          // ── Subheadline ────────────────────────────────────────────
          Text(
            slide.subheadline,
            textAlign: TextAlign.center,
            style: GoogleFonts.inter(
              fontSize: 14,
              fontWeight: FontWeight.w600,
              color: slide.iconColor,
              letterSpacing: 0.2,
            ),
          ),

          const SizedBox(height: 16),

          // ── Body copy ──────────────────────────────────────────────
          Text(
            slide.body,
            textAlign: TextAlign.center,
            style: GoogleFonts.inter(
              fontSize: 15,
              fontWeight: FontWeight.w400,
              color: AppColors.textSecondary,
              height: 1.55,
            ),
          ),
        ],
      ),
    );
  }
}
