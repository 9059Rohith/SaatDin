import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../models/claim_model.dart';
import '../../models/user_model.dart';
import '../../routes/app_routes.dart';
import '../../services/api_service.dart';
import '../../services/external_link_opener.dart';
import '../../services/tab_router.dart';
import '../../theme/app_colors.dart';

class ProfileScreen extends StatelessWidget {
  const ProfileScreen({super.key});

  static final ApiService _apiService = ApiService();
  static final Uri _adminConsoleUri = Uri.parse(
    'https://saatdin.onrender.com/admin',
  );
  static final Uri _apiDocsUri = Uri.parse('https://saatdin.onrender.com/docs');

  Future<_ProfileViewData> _loadProfileViewData() async {
    final user = await _apiService.getProfile('me');

    Map<String, dynamic> policy = <String, dynamic>{};
    List<Claim> claims = const <Claim>[];

    try {
      policy = await _apiService.getPolicy('me');
    } catch (_) {
      policy = <String, dynamic>{};
    }

    try {
      claims = await _apiService.getClaims('me');
    } catch (_) {
      claims = const <Claim>[];
    }

    return _ProfileViewData(user: user, policy: policy, claims: claims);
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<_ProfileViewData>(
      future: _loadProfileViewData(),
      builder: (context, snapshot) {
        if (snapshot.connectionState == ConnectionState.waiting) {
          return const Scaffold(
            backgroundColor: AppColors.scaffoldBackground,
            body: Center(child: CircularProgressIndicator()),
          );
        }

        if (snapshot.hasError || snapshot.data == null) {
          return const Scaffold(
            backgroundColor: AppColors.scaffoldBackground,
            body: Center(
              child: Text(
                'Failed to load profile. Please retry.',
                style: TextStyle(color: AppColors.textSecondary),
              ),
            ),
          );
        }

        final data = snapshot.data!;
        final user = data.user;
        final policy = data.policy;
        final claims = data.claims;
        final claimCountThisMonth = _claimCountForCurrentMonth(claims);
        final settledPayout = _settledPayoutTotal(claims);
        final perTriggerPayout = _readInt(policy, const ['perTriggerPayout']);
        final activePlan = _readString(policy, const [
          'plan',
        ], fallback: user.plan);
        final locationLabel = _buildLocationLabel(user);
        final policyStatusLabel =
            _readString(policy, const [
                  'status',
                ], fallback: 'active').toLowerCase() ==
                'active'
            ? 'Active policy'
            : 'Policy update pending';
        final nextBillingDate = _readString(policy, const ['nextBillingDate']);
        final renewalLabel = _renewalLabel(nextBillingDate);
        final contact = _formatPhone(user.phone);

        return Scaffold(
          backgroundColor: const Color(0xFFF4F7F5),
          body: Column(
            children: [
              _buildHeader(
                context,
                user,
                contact,
                policyStatusLabel,
                locationLabel,
              ),
              Expanded(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.only(bottom: 28),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      _buildCoverageBanner(
                        perTriggerPayout: perTriggerPayout,
                        activePlan: activePlan,
                        renewalLabel: renewalLabel,
                      ),
                      _buildSectionLabel('Insurance'),
                      _buildMenuGroup([
                        _MenuItemData(
                          icon: Icons.receipt_long_outlined,
                          iconBg: const Color(0xFFE1F5EE),
                          iconColor: const Color(0xFF0F6E56),
                          title: 'Claims history',
                          subtitle: '$claimCountThisMonth claims this month',
                          onTap: () => _switchToTab(context, 1),
                        ),
                        _MenuItemData(
                          icon: Icons.payments_outlined,
                          iconBg: const Color(0xFFE1F5EE),
                          iconColor: const Color(0xFF0F6E56),
                          title: 'Payouts',
                          subtitle:
                              '₹${NumberFormat('#,##0').format(settledPayout)} received',
                          onTap: () => _switchToTab(context, 3),
                        ),
                        _MenuItemData(
                          icon: Icons.workspace_premium_outlined,
                          iconBg: const Color(0xFFFAEEDA),
                          iconColor: const Color(0xFF854F0B),
                          title: 'Plans and pricing',
                          subtitle: activePlan.trim().isEmpty
                              ? 'Check available plans'
                              : '$activePlan plan active',
                          onTap: () => _switchToTab(context, 2),
                        ),
                      ]),
                      _buildSectionLabel('Preferences'),
                      _buildMenuGroup([
                        _MenuItemData(
                          icon: Icons.settings_outlined,
                          iconBg: const Color(0xFFF0F2F0),
                          iconColor: const Color(0xFF4A5E50),
                          title: 'Settings',
                          onTap: () => _showSimpleInfo(
                            context,
                            'Settings panel opened.',
                          ),
                        ),
                        _MenuItemData(
                          icon: Icons.dark_mode_outlined,
                          iconBg: const Color(0xFFF0F2F0),
                          iconColor: const Color(0xFF4A5E50),
                          title: 'Theme',
                          onTap: () => _showSimpleInfo(
                            context,
                            'Theme controls opened.',
                          ),
                        ),
                        _MenuItemData(
                          icon: Icons.grid_view_rounded,
                          iconBg: const Color(0xFFE6F1FB),
                          iconColor: const Color(0xFF185FA5),
                          title: 'Admin console',
                          subtitle: 'Open the live backend admin UI',
                          onTap: () => _openExternalLink(
                            context,
                            _adminConsoleUri,
                            fallbackMessage:
                                'Could not open the admin console.',
                          ),
                        ),
                        _MenuItemData(
                          icon: Icons.description_outlined,
                          iconBg: const Color(0xFFE1F5EE),
                          iconColor: const Color(0xFF0F6E56),
                          title: 'API docs',
                          subtitle: 'Open live backend routes and schemas',
                          onTap: () => _openExternalLink(
                            context,
                            _apiDocsUri,
                            fallbackMessage: 'Could not open the API docs.',
                          ),
                        ),
                      ]),
                      _buildSectionLabel('Account'),
                      _buildMenuGroup([
                        _MenuItemData(
                          icon: Icons.logout,
                          iconBg: const Color(0xFFFCEBEB),
                          iconColor: const Color(0xFFA32D2D),
                          title: 'Log out',
                          titleColor: const Color(0xFFC0392B),
                          onTap: () => _confirmLogout(context),
                        ),
                      ]),
                    ],
                  ),
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  // ─── Header band ───────────────────────────────────────────────────────────

  Widget _buildHeader(
    BuildContext context,
    User user,
    String contact,
    String policyStatus,
    String locationLabel,
  ) {
    return Container(
      color: AppColors.primary,
      child: SafeArea(
        bottom: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Top bar
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  _headerIconButton(
                    icon: Icons.arrow_back,
                    onTap: () => _switchToTab(context, 0),
                  ),
                  _headerIconButton(
                    icon: Icons.notifications_none,
                    onTap: () => _showNotificationsSheet(context),
                  ),
                ],
              ),
              const SizedBox(height: 20),
              // Profile row
              Row(
                children: [
                  Container(
                    width: 56,
                    height: 56,
                    decoration: BoxDecoration(
                      color: Colors.white,
                      shape: BoxShape.circle,
                      border: Border.all(
                        color: Colors.white.withValues(alpha: 0.4),
                        width: 2,
                      ),
                    ),
                    child: Center(
                      child: Text(
                        _displayInitial(user.name),
                        style: TextStyle(
                          color: AppColors.primary,
                          fontSize: 22,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          user.name,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontSize: 18,
                            fontWeight: FontWeight.w700,
                            color: Colors.white,
                            height: 1.2,
                          ),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          contact,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            fontSize: 12,
                            fontWeight: FontWeight.w400,
                            color: Colors.white.withValues(alpha: 0.72),
                            fontFamily: 'monospace',
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(width: 10),
                  _editButton(context),
                ],
              ),
              const SizedBox(height: 16),
              // Status pills
              Row(
                children: [
                  _statusPill(
                    dotColor: const Color(0xFF6EFFC4),
                    label: policyStatus,
                  ),
                  const SizedBox(width: 8),
                  _statusPill(
                    dotColor: const Color(0xFFFFD980),
                    label: locationLabel,
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _headerIconButton({
    required IconData icon,
    required VoidCallback onTap,
  }) {
    return InkWell(
      borderRadius: BorderRadius.circular(10),
      onTap: onTap,
      child: Container(
        width: 38,
        height: 38,
        decoration: BoxDecoration(
          color: Colors.white.withValues(alpha: 0.15),
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: Colors.white.withValues(alpha: 0.2)),
        ),
        child: Icon(icon, size: 20, color: Colors.white),
      ),
    );
  }

  Widget _editButton(BuildContext context) {
    return InkWell(
      borderRadius: BorderRadius.circular(8),
      onTap: () => _showSimpleInfo(context, 'Edit profile opened.'),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(
          color: Colors.white.withValues(alpha: 0.18),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: Colors.white.withValues(alpha: 0.25)),
        ),
        child: const Text(
          'Edit',
          style: TextStyle(
            fontSize: 12,
            fontWeight: FontWeight.w600,
            color: Colors.white,
          ),
        ),
      ),
    );
  }

  Widget _statusPill({required Color dotColor, required String label}) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(99),
        border: Border.all(color: Colors.white.withValues(alpha: 0.2)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 6,
            height: 6,
            decoration: BoxDecoration(color: dotColor, shape: BoxShape.circle),
          ),
          const SizedBox(width: 5),
          Text(
            label,
            style: const TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w500,
              color: Colors.white,
            ),
          ),
        ],
      ),
    );
  }

  // ─── Coverage banner ───────────────────────────────────────────────────────

  Widget _buildCoverageBanner({
    required int perTriggerPayout,
    required String activePlan,
    required String renewalLabel,
  }) {
    return Container(
      margin: const EdgeInsets.fromLTRB(16, 16, 16, 0),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE2EBE6)),
      ),
      child: Row(
        children: [
          Container(
            width: 38,
            height: 38,
            decoration: BoxDecoration(
              color: const Color(0xFFE1F5EE),
              borderRadius: BorderRadius.circular(10),
            ),
            child: const Icon(
              Icons.verified_user_outlined,
              size: 20,
              color: Color(0xFF0F6E56),
            ),
          ),
          const SizedBox(width: 12),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                "This week's coverage",
                style: TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w500,
                  color: Color(0xFF6B8A77),
                ),
              ),
              const SizedBox(height: 2),
              Text(
                '₹$perTriggerPayout / day',
                style: TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                  color: Color(0xFF1A2E25),
                ),
              ),
              const SizedBox(height: 1),
              Text(
                renewalLabel,
                style: TextStyle(fontSize: 10, color: Colors.grey.shade500),
              ),
            ],
          ),
          const Spacer(),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
            decoration: BoxDecoration(
              color: const Color(0xFFE1F5EE),
              borderRadius: BorderRadius.circular(99),
            ),
            child: Text(
              activePlan,
              style: TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w700,
                color: Color(0xFF0F6E56),
              ),
            ),
          ),
        ],
      ),
    );
  }

  // ─── Section label ─────────────────────────────────────────────────────────

  Widget _buildSectionLabel(String label) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 20, 20, 8),
      child: Text(
        label.toUpperCase(),
        style: const TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w700,
          color: Color(0xFF8BA897),
          letterSpacing: 0.08 * 11,
        ),
      ),
    );
  }

  // ─── Menu group ────────────────────────────────────────────────────────────

  Widget _buildMenuGroup(List<_MenuItemData> items) {
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFFE2EBE6)),
      ),
      clipBehavior: Clip.hardEdge,
      child: Column(
        children: List.generate(items.length, (i) {
          return Column(
            children: [
              _buildMenuRow(items[i]),
              if (i < items.length - 1)
                const Divider(
                  height: 0,
                  thickness: 0.5,
                  indent: 56,
                  color: Color(0xFFE8F0EB),
                ),
            ],
          );
        }),
      ),
    );
  }

  Widget _buildMenuRow(_MenuItemData item) {
    return InkWell(
      onTap: item.onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 13),
        child: Row(
          children: [
            Container(
              width: 36,
              height: 36,
              decoration: BoxDecoration(
                color: item.iconBg,
                borderRadius: BorderRadius.circular(9),
              ),
              child: Icon(item.icon, size: 18, color: item.iconColor),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    item.title,
                    style: TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w600,
                      color: item.titleColor ?? const Color(0xFF1A2E25),
                    ),
                  ),
                  if (item.subtitle != null) ...[
                    const SizedBox(height: 1),
                    Text(
                      item.subtitle!,
                      style: const TextStyle(
                        fontSize: 11,
                        color: Color(0xFF8BA897),
                      ),
                    ),
                  ],
                ],
              ),
            ),
            if (item.badge != null) ...[
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: const Color(0xFFE1F5EE),
                  borderRadius: BorderRadius.circular(99),
                ),
                child: Text(
                  item.badge!,
                  style: const TextStyle(
                    fontSize: 10,
                    fontWeight: FontWeight.w700,
                    color: Color(0xFF0F6E56),
                  ),
                ),
              ),
              const SizedBox(width: 6),
            ],
            const Icon(Icons.chevron_right, size: 18, color: Color(0xFFB0C4B8)),
          ],
        ),
      ),
    );
  }

  // ─── Actions ───────────────────────────────────────────────────────────────

  void _showNotificationsSheet(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (_) {
        return ListView(
          shrinkWrap: true,
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 20),
          children: const [
            ListTile(
              leading: Icon(Icons.verified_outlined),
              title: Text('Profile verification completed'),
              subtitle: Text('Your account details are fully up to date'),
            ),
            ListTile(
              leading: Icon(Icons.shield_outlined),
              title: Text('Security reminder'),
              subtitle: Text('Review device activity once every week'),
            ),
          ],
        );
      },
    );
  }

  void _showSimpleInfo(BuildContext context, String message) {
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _openExternalLink(
    BuildContext context,
    Uri uri, {
    required String fallbackMessage,
  }) async {
    final opened = await openExternalLink(uri);
    if (!opened && context.mounted) {
      _showSimpleInfo(context, fallbackMessage);
    }
  }

  void _switchToTab(BuildContext context, int index) {
    TabRouter.switchTo(index);
    Navigator.of(context).popUntil((route) => route.isFirst);
  }

  void _confirmLogout(BuildContext context) {
    showDialog<void>(
      context: context,
      builder: (dialogContext) {
        return AlertDialog(
          title: const Text('Log out'),
          content: const Text(
            'Are you sure you want to log out of this account?',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () {
                Navigator.pop(dialogContext);
                Navigator.pushNamedAndRemoveUntil(
                  context,
                  AppRoutes.welcome,
                  (route) => false,
                );
              },
              child: const Text('Log out'),
            ),
          ],
        );
      },
    );
  }

  String _readString(
    Map<String, dynamic> raw,
    List<String> keys, {
    String fallback = '',
  }) {
    for (final key in keys) {
      final value = raw[key];
      if (value == null) continue;
      final parsed = value.toString().trim();
      if (parsed.isNotEmpty) return parsed;
    }
    return fallback;
  }

  int _readInt(
    Map<String, dynamic> raw,
    List<String> keys, {
    int fallback = 0,
  }) {
    for (final key in keys) {
      final value = raw[key];
      if (value == null) continue;
      if (value is num) return value.toInt();
      if (value is String) {
        final parsed = int.tryParse(value.replaceAll(',', '').trim());
        if (parsed != null) return parsed;
      }
    }
    return fallback;
  }

  int _claimCountForCurrentMonth(List<Claim> claims) {
    final now = DateTime.now();
    return claims.where((claim) {
      final claimDate = claim.date;
      return claimDate.year == now.year && claimDate.month == now.month;
    }).length;
  }

  double _settledPayoutTotal(List<Claim> claims) {
    return claims
        .where((claim) => claim.status == ClaimStatus.settled)
        .fold<double>(0, (sum, claim) => sum + claim.amount);
  }

  String _renewalLabel(String nextBillingDateRaw) {
    final parsed = DateTime.tryParse(nextBillingDateRaw);
    if (parsed == null) return 'Renewal date unavailable';
    return 'Renews ${DateFormat('EEE, d MMM').format(parsed.toLocal())}';
  }

  String _buildLocationLabel(User user) {
    final platform = user.platform.trim();
    final zone = user.zone.trim();
    final pincode = user.zonePincode.trim();
    if (platform.isEmpty && zone.isEmpty && pincode.isEmpty) {
      return 'Location unavailable';
    }

    final pieces = <String>[];
    if (platform.isNotEmpty) pieces.add(platform);
    if (zone.isNotEmpty) pieces.add('Zone: $zone');
    if (pincode.isNotEmpty) pieces.add('Area: $pincode');
    return pieces.join(' · ');
  }

  String _formatPhone(String phone) {
    final digits = phone.replaceAll(RegExp(r'\D'), '');
    if (digits.length == 10) {
      return '+91 ${digits.substring(0, 5)} ${digits.substring(5)}';
    }
    return phone.trim().isEmpty ? 'No contact number' : phone.trim();
  }

  String _displayInitial(String name) {
    final trimmed = name.trim();
    if (trimmed.isEmpty) return '?';
    return trimmed.substring(0, 1).toUpperCase();
  }
}

// ─── Data class for menu items ────────────────────────────────────────────────

class _MenuItemData {
  final IconData icon;
  final Color iconBg;
  final Color iconColor;
  final String title;
  final Color? titleColor;
  final String? subtitle;
  final String? badge;
  final VoidCallback onTap;

  const _MenuItemData({
    required this.icon,
    required this.iconBg,
    required this.iconColor,
    required this.title,
    required this.onTap,
    this.titleColor,
    this.subtitle,
    this.badge,
  });
}

class _ProfileViewData {
  const _ProfileViewData({
    required this.user,
    required this.policy,
    required this.claims,
  });

  final User user;
  final Map<String, dynamic> policy;
  final List<Claim> claims;
}
