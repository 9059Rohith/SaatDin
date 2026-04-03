import 'package:flutter/material.dart';
import '../../theme/app_colors.dart';
import '../../services/tab_router.dart';
import 'home/home_screen.dart';
import 'claims/claims_screen.dart';
import 'coverage/coverage_screen.dart';
import 'payouts/payouts_screen.dart';
import 'profile/profile_screen.dart';

class MainShell extends StatefulWidget {
  const MainShell({super.key});

  @override
  State<MainShell> createState() => _MainShellState();
}

class _MainShellState extends State<MainShell> {
  int _currentIndex = 0;

  @override
  void initState() {
    super.initState();
    TabRouter.resetToHome();
    _currentIndex = TabRouter.tabIndex.value;
    TabRouter.tabIndex.addListener(_handleExternalTabChange);
  }

  @override
  void dispose() {
    TabRouter.tabIndex.removeListener(_handleExternalTabChange);
    super.dispose();
  }

  void _handleExternalTabChange() {
    if (!mounted) return;
    final nextIndex = TabRouter.tabIndex.value;
    if (nextIndex == _currentIndex) return;
    if (nextIndex < 0 || nextIndex >= _screens.length) return;
    setState(() {
      _currentIndex = nextIndex;
    });
  }

  List<Widget> get _screens => const [
        HomeScreen(),
        ClaimsScreen(),
        CoverageScreen(),
        PayoutsScreen(),
        ProfileScreen(),
      ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: IndexedStack(
        index: _currentIndex,
        children: _screens,
      ),
      bottomNavigationBar: Container(
        decoration: BoxDecoration(
          color: AppColors.background,
          boxShadow: [
            BoxShadow(
              color: Colors.black.withValues(alpha: 0.06),
              blurRadius: 20,
              offset: const Offset(0, -4),
            ),
          ],
        ),
        child: SafeArea(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 2),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceEvenly,
              children: [
                _buildNavItem(
                  index: 0,
                  icon: Icons.home_outlined,
                  activeIcon: Icons.home_rounded,
                  label: 'HOME',
                ),
                _buildNavItem(
                  index: 1,
                  icon: Icons.description_outlined,
                  activeIcon: Icons.description_rounded,
                  label: 'CLAIMS',
                ),
                _buildNavItem(
                  index: 2,
                  icon: Icons.verified_user_outlined,
                  activeIcon: Icons.verified_user_rounded,
                  label: 'COVERAGE',
                ),
                _buildNavItem(
                  index: 3,
                  icon: Icons.payments_outlined,
                  activeIcon: Icons.payments_rounded,
                  label: 'PAYOUTS',
                ),
                _buildNavItem(
                  index: 4,
                  icon: Icons.account_circle_outlined,
                  activeIcon: Icons.account_circle,
                  label: 'PROFILE',
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildNavItem({
    required int index,
    required IconData icon,
    required IconData activeIcon,
    required String label,
  }) {
    final isActive = _currentIndex == index;

    return GestureDetector(
      onTap: () {
        setState(() {
          _currentIndex = index;
          TabRouter.switchTo(index);
        });
      },
      behavior: HitTestBehavior.opaque,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              isActive ? activeIcon : icon,
              color: isActive ? AppColors.primary : AppColors.navInactive,
              size: 28,
            ),
            const SizedBox(height: 2),
            Text(
              label,
              style: TextStyle(
                fontSize: 9,
                fontWeight: FontWeight.w700,
                color: isActive ? AppColors.primary : AppColors.navInactive,
                letterSpacing: 0.6,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
