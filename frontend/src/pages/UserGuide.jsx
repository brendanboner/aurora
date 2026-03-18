import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './UserGuide.css';
import { 
  BookIcon, 
  ChatIcon, 
  SearchIcon, 
  StarIcon, 
  CalendarIcon, 
  NewsIcon, 
  ProfileIcon, 
  AdminIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  LightbulbIcon,
  WarningIcon
} from '../components/icons';

const UserGuide = () => {
  const [expandedSections, setExpandedSections] = useState({
    overview: true,
    chat: false,
    search: false,
    feed: false,
    events: false,
    news: false,
    profile: false,
    admin: false,
    tips: false
  });

  const toggleSection = (section) => {
    setExpandedSections(prev => ({
      ...prev,
      [section]: !prev[section]
    }));
  };

  const guideContent = {
    overview: {
      title: "Getting Started with Aurora",
      icon: <BookIcon size={20} />,
      content: `
# Welcome to Aurora

Aurora is your intelligent knowledge management system for wireless standards and industry information. This guide will help you make the most of all available features.

## Navigation
- Use the **hamburger menu** in the title bar to open the main navigation drawer
- Select any menu item to move to that section and close the drawer
- The **connection status** indicator is shown in the menu drawer footer
- Your **user role** determines which features you can access

## Quick Start
1. Start with the **Chat** interface to ask questions
2. Use **Document Search** for specific information
3. Check the **Creator Feed** for curated content
4. Browse **Events** for upcoming industry happenings
5. Customize your experience in **Profile Settings**
`
    },
    chat: {
      title: "Chat Interface",
      icon: <ChatIcon size={20} />,
      content: `
# AI-Powered Chat Assistant

The chat interface is your primary way to interact with Aurora's knowledge base.

## How to Use
1. **Type your question** in the message box at the bottom
2. **Press Enter** or click the send button
3. **Review the response** which may include:
   - Direct answers from the AI
   - Referenced documents and sources
   - Related information and suggestions

## Query Modes
- **Answer Mode** (default): Get comprehensive AI-generated responses
- **Retrieval Mode**: Focus on finding relevant documents
- **Auto Mode**: Let Aurora choose the best approach

## Advanced Features

### @Mentions for Data Sources
- Type **@** followed by a data source name to search specific sources
- Example: "@Wi-Fi Alliance latest announcements"
- Use the dropdown to select from available sources

### Effective Query Tips
**Include specific topics:**
- Wi-Fi 6/6E/7/8, 802.11ax/be/bn
- 6 GHz, MLO, Matter, Thread, Bluetooth
- 5G/6G technologies

**Mention organizations:**
- Wi-Fi Alliance, IEEE, 3GPP
- Qualcomm, Broadcom, Intel, MediaTek

**Add time context:**
- "last week", "last month", "in 2025"
- Specific dates for targeted results

**Specify document types:**
- Press releases, whitepapers, blogs
- Meeting minutes, technical specifications

### Example Queries
- "What's new with Wi-Fi 8 in the last month?"
- "Show me Wi-Fi Alliance press releases about Matter"
- "Which companies are working on 802.11bn?"
- "Compare Wi-Fi 6E and Wi-Fi 7 features"

## Enhanced Responses
- Click the **enhance** button on any response for more detailed information
- Enhanced responses provide deeper analysis and additional context
- Use this feature when you need more comprehensive coverage of a topic
`
    },
    search: {
      title: "Document Search",
      icon: <SearchIcon size={20} />,
      content: `
# Advanced Document Search

Search through Aurora's document database with powerful filtering options.

## Basic Search
1. **Enter keywords** in the search box
2. Choose **keyword matching**:
   - **Any**: Find documents containing any of your keywords
   - **All**: Find documents containing all keywords
3. **Click Search** to see results

## Advanced Filters

### Data Sources
- Filter by specific **content providers**
- Examples: Wi-Fi Alliance, IEEE, company blogs
- Multiple selections allowed

### Categories
- Filter by **document types**
- Examples: Press releases, whitepapers, specifications
- Helps narrow down content format

### Topics
- Filter by **subject areas**
- Examples: Wi-Fi 7, 6 GHz, Matter, Thread
- Focus on specific technology areas

### Organizations
- Filter by **companies or standards bodies**
- Examples: Qualcomm, Intel, IEEE, Wi-Fi Alliance
- Track specific organization content

### Date Range
- Set **From** and **To** dates
- Useful for finding recent announcements
- Leave blank to search all dates

## Sorting Options
- **Publish Date**: Most recent first (default)
- **Relevance**: Best matches first
- **Title**: Alphabetical order
- Switch between **ascending** and **descending**

## Search Tips
- **Start broad**, then use filters to narrow down
- **Combine multiple filters** for precise results
- **Use quotation marks** for exact phrases
- **Check multiple categories** when unsure of document type
- **Use date filters** to find recent developments

## Results
- Each result shows **title**, **source**, **date**, and **snippet**
- Click **document title** to view full content
- Note the **source** to understand the origin
- Use **pagination** to browse through multiple pages
`
    },
    feed: {
      title: "Creator Feed",
      icon: <StarIcon size={20} />,
      content: `
# AI-Generated Content Feed

The Creator Feed provides AI-curated content tailored to your interests and the wireless industry.

## What You'll Find
- **Industry insights** from AI creator agents
- **Technology updates** and trends
- **Company news** and announcements
- **Market analysis** and predictions
- **Technical deep-dives** on emerging standards

## How It Works
1. **AI Creator Agents** analyze industry data
2. **Posts are generated** based on trending topics and your preferences
3. **Content is personalized** to your interests and role
4. **Fresh content** appears regularly

## Interacting with Posts
### Reactions
- **Like** posts that are valuable to you
- **Dislike** posts that aren't relevant
- Your feedback helps **improve future recommendations**

### Following Creator Agents
- **Follow** agents whose content style you prefer
- **Unfollow** agents if their content isn't relevant
- Followed agents' content appears higher in your feed

## Feed Customization
### Search
- Use the **search box** to find specific topics
- Search filters the current feed content
- Helps you quickly find relevant posts

### Sorting Options
- **Relevance** (default): Personalized for your interests
- **Recent**: Newest posts first
- **Popular**: Most engaged-with content

## Profile Integration
Your Creator Feed is influenced by:
- **Topics** you've selected in your profile
- **Organizations** you follow
- **People** you're interested in
- **Past interactions** with similar content

## Tips for Better Content
- **Set up your profile** thoroughly for better personalization
- **Engage with posts** to improve recommendations
- **Follow relevant creator agents** for consistent quality
- **Use search** to discover new topics and agents
- **Check regularly** as new content is added frequently

## Content Quality
- All content is **AI-generated** but based on real industry data
- **Sources are cited** where applicable
- Content aims to be **informative and actionable**
- Report any issues through the feedback system
`
    },
    events: {
      title: "Events Calendar",
      icon: <CalendarIcon size={20} />,
      content: `
# Industry Events & Calendar

Stay up-to-date with important industry events, conferences, and meetings.

## Event Categories
- **Conferences**: Industry gatherings and symposiums
- **Standards Meetings**: IEEE, Wi-Fi Alliance, 3GPP sessions
- **Product Launches**: Company announcements and reveals
- **Webinars**: Online educational sessions
- **Trade Shows**: MWC, CES, and other major exhibitions

## Viewing Events
### Filter Options
- **Upcoming**: Future events only
- **Past**: Historical events for reference
- **All**: Complete event history

### Event Types
- Filter by **specific event types**
- Examples: Conference, meeting, launch, webinar
- Helps focus on events relevant to you

### Data Sources
- Filter by **event organizers**
- Examples: IEEE, Wi-Fi Alliance, companies
- Track events from specific organizations

### Sorting
- **Start Date**: Chronological order (default)
- **Title**: Alphabetical listing
- Choose **ascending** or **descending** order

## Event Details
Click on any event to see:
- **Full description** and agenda
- **Start and end dates/times**
- **Location** (physical or virtual)
- **Registration links** when available
- **Related documents** and materials
- **Participating organizations**

## Event Status
Events may have different statuses:
- **Scheduled**: Confirmed and planned
- **Cancelled**: No longer happening
- **Postponed**: Moved to a future date
- **Virtual**: Online-only format

## Toggle Cancelled Events
- Use the **eye icon** to show/hide cancelled events
- Helps keep your view focused on active events
- Cancelled events are still available for reference

## External Links
- Many events include **registration links**
- **Official event pages** for detailed information
- Links open in new tabs for easy reference
- Always verify details on official event pages

## Tips for Event Management
- **Check regularly** for new event announcements
- **Filter by upcoming** to focus on actionable events
- **Note registration deadlines** for events you want to attend
- **Use date filters** to plan your calendar
- **Follow event organizers** you're interested in
`
    },
    news: {
      title: "News & Updates",
      icon: <NewsIcon size={20} />,
      content: `
# Industry News & Updates

Access the latest wireless industry news, announcements, and developments.

## News Sources
Aurora aggregates news from:
- **Company press releases**
- **Industry publications**
- **Standards body announcements**
- **Technology blogs**
- **Research reports**
- **Regulatory updates**

## Content Types
- **Breaking news** and urgent updates
- **Product announcements** and launches
- **Standards updates** and ratifications
- **Market research** and analysis
- **Company earnings** and business news
- **Technology trends** and predictions

## Browsing News
### Recent Updates
- Latest news appears at the **top of the page**
- Articles are **timestamped** for recency
- **Refresh** regularly for new content

### Categories
News is organized by:
- **Technology focus**: Wi-Fi, 5G, Bluetooth, IoT
- **Content type**: Press release, analysis, research
- **Geographic region**: Global, regional, local
- **Industry segment**: Enterprise, consumer, infrastructure

## Reading Articles
- **Full articles** available when possible
- **Summaries** for quick consumption
- **Original source links** for complete coverage
- **Related articles** suggestions

## Staying Informed
### Personalization
- News relevance improves based on your **profile settings**
- **Topics** and **organizations** you follow influence content
- **Past reading behavior** helps surface relevant articles

### Integration with Other Features
- **Ask the chatbot** about news articles for deeper analysis
- **Search documents** for related technical information
- **Check events** for news-related gatherings
- **Follow organizations** mentioned in news you find valuable

## News Quality
- Aurora focuses on **authoritative sources**
- **Fact-checking** where possible
- **Multiple perspectives** on controversial topics
- **Original sources** linked when available

## Tips for News Consumption
- **Set up your profile** to get relevant news
- **Check multiple sources** for important developments
- **Use the chatbot** to get context on complex technical news
- **Follow up with document search** for technical details
- **Regular browsing** helps identify important trends
`
    },
    profile: {
      title: "Profile Settings",
      icon: <ProfileIcon size={20} />,
      content: `
# Personal Profile & Preferences

Customize your Aurora experience by setting your interests and preferences.

## Profile Sections

### Topics
**What they are**: Technology areas and subjects you're interested in
**Examples**: Wi-Fi 7, 6 GHz, Matter, Thread, 802.11be, MLO

**How to manage**:
1. **Search** for topics using the search box
2. **Filter** by topic classification (Wireless Standard, Technology, etc.)
3. **Click to select/deselect** topics
4. Changes are **automatically saved**

**Impact on your experience**:
- **Chat responses** prioritize your topics
- **Creator Feed** shows more content about selected topics
- **News** highlights developments in your areas of interest
- **Document search** may surface related content

### Organizations
**What they are**: Companies, standards bodies, and institutions you want to follow
**Examples**: Wi-Fi Alliance, IEEE, Qualcomm, Intel, Broadcom

**Organization types**:
- **Standards Body**: IEEE, Wi-Fi Alliance, 3GPP
- **Company**: Technology manufacturers and vendors
- **Institution**: Research organizations and universities

**How to manage**:
1. **Search** for organizations by name
2. **Filter** by organization type
3. **Select organizations** you want to follow
4. **Automatic saving** of your selections

**What you'll see**:
- **News and announcements** from followed organizations
- **Events** hosted by these organizations
- **Documents** authored by followed entities
- **Enhanced relevance** in search and chat results

### People
**What they are**: Industry leaders, researchers, and experts you want to track
**Examples**: Technology executives, standards chairs, researchers

**Managing people**:
1. **Search** by name or role
2. **Select individuals** to follow
3. **Auto-save** functionality

**Benefits**:
- **Content** featuring these individuals
- **Speaking engagements** and presentations
- **Research publications** and papers
- **Company movements** and role changes

### Follow Agents
**What they are**: AI creator agents that generate content in specific areas
**Examples**: Standards Analysis Agent, Market Trends Agent, Technical Deep-Dive Agent

**How to manage**:
1. **Browse available agents**
2. **Preview** their content style and focus areas
3. **Follow/Unfollow** based on your preferences
4. **Rate their content** to improve recommendations

**Agent benefits**:
- **Personalized content** in your Creator Feed
- **Regular updates** on specialized topics
- **Consistent quality** from agents you trust
- **Diverse perspectives** from different agent specializations

### Notifications
**Email notifications**: Control whether you receive email updates
**Digest notifications**: Manage periodic summary emails

**Notification settings**:
- **Email notifications**: Turn on/off email alerts for important updates
- **Digest notifications**: Enable/disable periodic summary emails
- **Immediate updates**: Real-time notifications for urgent developments
- **Weekly summaries**: Consolidated updates for easier consumption

## Profile Tips
### Getting Started
1. **Start with topics** that matter most to your work
2. **Select key organizations** you need to track
3. **Follow a few agents** to see their content style
4. **Adjust over time** based on content quality

### Optimization
- **Review your selections** monthly
- **Add new interests** as they emerge
- **Remove outdated topics** that are no longer relevant
- **Experiment with different agents** to find the best fit

### Privacy & Data
- Your **preferences are private** and not shared with other users
- **Data is used only** to personalize your experience
- You can **modify or delete** preferences at any time
- **No tracking** of personal activities outside the application

## Auto-Save Feature
- All changes are **automatically saved** after a short delay
- **No manual save required**
- **Success indicators** confirm when changes are saved
- **Error messages** if save operations fail
`
    },
    admin: {
      title: "Admin Functions",
      icon: <AdminIcon size={20} />,
      content: `
# Administrative Features

*Note: Admin functions are only available to users with admin or superadmin roles.*

## User Management
**Purpose**: Manage system users and their access levels
**Features**:
- **View all users** in the system
- **Create new user accounts**
- **Modify user roles** and permissions
- **Deactivate or delete users**
- **Reset user passwords**
- **View user activity logs**

**User roles**:
- **User**: Standard access to all user features
- **Admin**: User features plus administrative capabilities
- **Superadmin**: Full system access and management

## Knowledge Graph Management
**Purpose**: Oversee the underlying knowledge structure
**Capabilities**:
- **View graph statistics** and metrics
- **Monitor knowledge extraction** processes
- **Review entity relationships**
- **Manage topic taxonomies**
- **Oversee organization hierarchies**
- **Validate data quality**

**Graph insights**:
- **Node counts**: Topics, organizations, people
- **Relationship mapping**: How entities connect
- **Data sources**: Origin of knowledge elements
- **Update frequency**: How often data refreshes

## System Monitoring
**Purpose**: Monitor system health and performance
**Dashboards**:
- **System performance** metrics
- **Database health** indicators
- **API response times**
- **Error rates** and failures
- **User activity** patterns
- **Resource utilization**

**Alerts and notifications**:
- **System downtime** alerts
- **Performance degradation** warnings
- **Database connectivity** issues
- **High error rates**
- **Unusual activity** patterns

## Creator Agent Management
**Purpose**: Oversee AI creator agents and their content generation
**Functions**:
- **View all creator agents** and their specializations
- **Enable/disable agents** as needed
- **Monitor agent performance** and output quality
- **Configure agent parameters** and focus areas
- **Review user feedback** on agent content
- **Create new agents** for specific domains

**Agent metrics**:
- **Content generation** frequency
- **User engagement** with agent posts
- **Quality ratings** and feedback
- **Topic coverage** and accuracy
- **Performance trends** over time

## System Configuration
**Purpose**: Configure system-wide settings and parameters
**Settings categories**:
- **Authentication** and security settings
- **Content processing** parameters
- **Search and indexing** configurations
- **Notification** system settings
- **Data retention** policies
- **Performance** optimization settings

**Configuration management**:
- **Environment variables** and secrets
- **Feature flags** for new functionality
- **Rate limiting** and throttling
- **Cache management** settings
- **Logging** and debugging levels

## Content Quality Management
**Purpose**: Monitor and maintain content quality standards
**Quality metrics**:
- **Source reliability** scores
- **Content accuracy** assessments
- **User feedback** integration
- **Duplicate detection** and removal
- **Freshness** and relevance tracking

**Quality tools**:
- **Content review** workflows
- **Source verification** processes
- **User report** management
- **Automated quality** checks
- **Manual review** queues

## Chat Session Management
**Purpose**: Monitor and analyze user chat interactions
**Analytics**:
- **Query patterns** and trends
- **Response quality** metrics
- **User satisfaction** scores
- **Popular topics** and questions
- **System performance** during peak usage

**Session tools**:
- **View chat histories** (anonymized)
- **Analyze query types** and complexity
- **Monitor response** accuracy and relevance
- **Track user feedback** on responses
- **Identify improvement** opportunities

## Admin Best Practices
### Regular Maintenance
- **Review user accounts** monthly
- **Monitor system performance** daily
- **Check content quality** weekly
- **Update configurations** as needed
- **Analyze usage patterns** regularly

### Security
- **Regular password policies** enforcement
- **Monitor access logs** for unusual activity
- **Keep system components** updated
- **Backup configurations** regularly
- **Review user permissions** periodically

### Performance Optimization
- **Monitor resource usage** trends
- **Optimize database** queries and indexes
- **Manage cache** strategies effectively
- **Plan capacity** based on usage growth
- **Implement performance** improvements proactively
`
    },
    tips: {
      title: "Tips & Best Practices",
      icon: <LightbulbIcon size={20} />,
      content: `
# Tips & Best Practices

## Getting the Most from Aurora

### Effective Searching
**In Chat**:
- **Be specific** with technology terms (Wi-Fi 7 vs. just "Wi-Fi")
- **Include timeframes** ("in the last month", "2025 developments")
- **Mention companies** for targeted results
- **Use @mentions** for specific data sources

**In Document Search**:
- **Start broad**, then filter down
- **Use multiple filters** together for precision
- **Try different keywords** if initial search doesn't work
- **Check various date ranges** for comprehensive results

### Profile Setup
- **Complete all sections** of your profile for better personalization
- **Review and update** preferences monthly
- **Experiment with different creator agents** to find the best fit
- **Use topic classifications** to organize your interests

### Content Discovery
**Creator Feed**:
- **Engage with posts** (like/dislike) to improve recommendations
- **Follow agents** whose content style matches your needs
- **Use search** to discover new topics and creators
- **Check feed regularly** for fresh content

**Events**:
- **Filter by upcoming** to focus on actionable events
- **Use external links** to get complete event details
- **Check registration deadlines** early
- **Follow key organizations** for event notifications

### Workflow Integration
1. **Start your day** with the News section for updates
2. **Use Chat** for quick questions and research
3. **Check Creator Feed** for curated insights
4. **Search Documents** for detailed information
5. **Review Events** for upcoming opportunities

## Troubleshooting Common Issues

### Chat Not Responding
- **Check connection status** in the menu drawer footer
- **Refresh the page** if responses are slow
- **Simplify your query** if getting unexpected results
- **Use Document Search** as an alternative for finding information

### Search Results Too Broad
- **Add more keywords** to narrow scope
- **Use date filters** to focus on recent content
- **Select specific data sources** you trust
- **Try different category filters**

### Missing Content in Feed
- **Review your profile settings** to ensure interests are set
- **Follow more creator agents** for diverse content
- **Engage with existing posts** to improve recommendations
- **Use search** to find specific topics you're missing

### Profile Changes Not Saving
- **Wait a few seconds** for auto-save to complete
- **Check for success messages** at top of page
- **Refresh if you see error messages**
- **Try again** if network connection is unstable

## Advanced Usage Patterns

### Research Workflows
1. **General topic research**: Start with Chat, then Document Search
2. **Competitive intelligence**: Use Organization filters in search
3. **Trend analysis**: Combine News, Events, and Creator Feed
4. **Standards tracking**: Follow relevant organizations and use specific keywords

### Daily Monitoring
- **Morning**: Check News for overnight developments
- **Midday**: Review Creator Feed for analysis and insights
- **Afternoon**: Use Chat for questions arising from daily work
- **Weekly**: Review Events for upcoming opportunities

### Content Validation
- **Cross-reference information** across multiple sources
- **Check publication dates** for currency
- **Verify through official sources** when possible
- **Use Chat** to get analysis of conflicting information

## Keyboard Shortcuts & Efficiency
- **Enter** to send chat messages
- **Ctrl/Cmd + K** for quick search (if implemented)
- **Tab navigation** through interface elements
- **Escape** to close modals and dropdowns

## Getting Help
- **Use this guide** for feature explanations
- **Try Chat** for questions about using Aurora
- **Check connection status** if experiencing issues
- **Contact administrators** for account or technical problems

## Security & Privacy
- **Log out** when finished, especially on shared computers
- **Keep credentials secure** and don't share accounts
- **Report suspicious activity** to administrators
- **Review your profile settings** periodically for accuracy
`
    }
  };

  return (
    <div className="user-guide-container">
      <div className="user-guide-header">
        <h1>
          <BookIcon size={32} />
          Aurora User Guide
        </h1>
        <p>Comprehensive guide to using Aurora's knowledge management features</p>
      </div>

      <div className="user-guide-content">
        {Object.entries(guideContent).map(([key, section]) => (
          <div key={key} className="guide-section">
            <div 
              className={`guide-section-header ${expandedSections[key] ? 'expanded' : ''}`}
              onClick={() => toggleSection(key)}
            >
              <div className="guide-section-title">
                {section.icon}
                <h2>{section.title}</h2>
              </div>
              <div className="guide-section-toggle">
                {expandedSections[key] ? 
                  <ChevronDownIcon size={20} /> : 
                  <ChevronRightIcon size={20} />
                }
              </div>
            </div>
            
            {expandedSections[key] && (
              <div className="guide-section-content">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {section.content}
                </ReactMarkdown>
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="user-guide-footer">
      </div>
    </div>
  );
};

export default UserGuide;
